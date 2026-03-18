"""
CNP-OPS-004 — Fleet Scoring Engine.

Computes per-node health scores from available signals.
Weights per CNP-OPS-004 spec section 8.1:
  reliability:     35%
  performance:     25%
  security:        20%
  maintainability: 10%
  responsiveness:  10%

Score inputs available post-Phase 2 (safe to compute now):
  - heartbeat regularity (from heartbeats table)
  - queue depth trends (heartbeats)
  - RSSI trends (heartbeats)
  - battery trends (heartbeats)
  - offline transitions (heartbeat_daily_summary)
  - active anomaly count (ops_anomalies)
  - firmware version presence (nodes)
  - OTA support flag (nodes)
  - last_seen recency (nodes)

Inputs deferred (Phase 3+):
  - dead_letter_count (P3-06)
  - command lag (P3-05)
  - auth failure rate (P1-07 + P4-05)
  - signed message adoption (P3-02)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from .db import (
    get_all_node_scores,
    get_anomalies,
    get_latest_score,
    get_recent_heartbeats,
    persist_health_score,
)
from .models import HealthScoreRecord, ScopeType

log = logging.getLogger("cnp.ops.scoring")

# Score weights (must sum to 1.0)
_WEIGHTS = {
    "reliability":     0.35,
    "performance":     0.25,
    "security":        0.20,
    "maintainability": 0.10,
    "responsiveness":  0.10,
}

assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9, "Score weights must sum to 1.0"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------
#  Sub-score calculators
# ----------------------------------------------------------------

def _reliability_score(
    heartbeats: list[dict[str, Any]],
    active_anomalies: list[dict[str, Any]],
    node: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """
    Factors: heartbeat regularity, offline transitions, active anomaly count.
    Returns (score 0-100, evidence dict).
    """
    score = 100.0
    evidence: dict[str, Any] = {}

    # Heartbeat regularity: penalize if < 5 heartbeats in the window
    hb_count = len(heartbeats)
    evidence["heartbeat_count"] = hb_count
    if hb_count == 0:
        return 0.0, {"reason": "no_heartbeats"}
    if hb_count < 3:
        score -= 30.0
        evidence["regularity_penalty"] = 30

    # Active anomaly penalty
    reliability_anomalies = [
        a for a in active_anomalies
        if a.get("category") in ("reliability", "connectivity")
    ]
    anomaly_penalty = min(40.0, len(reliability_anomalies) * 15.0)
    score -= anomaly_penalty
    evidence["reliability_anomaly_count"] = len(reliability_anomalies)
    evidence["anomaly_penalty"] = anomaly_penalty

    # Node status penalty
    status = node.get("status", "unknown")
    if status == "offline":
        score -= 25.0
        evidence["status_penalty"] = 25
    elif status == "degraded":
        score -= 10.0
        evidence["status_penalty"] = 10

    return max(0.0, min(100.0, score)), evidence


def _performance_score(
    heartbeats: list[dict[str, Any]],
    active_anomalies: list[dict[str, Any]],
) -> tuple[float, dict[str, Any]]:
    """
    Factors: queue depth trend, RSSI, active performance anomalies.
    """
    score = 100.0
    evidence: dict[str, Any] = {}

    if not heartbeats:
        return 50.0, {"reason": "no_data"}

    # Queue depth (use last 5)
    recent = heartbeats[-5:]
    queue_depths = [r.get("queue_depth") or 0 for r in recent]
    avg_queue = sum(queue_depths) / len(queue_depths)
    evidence["avg_queue_depth"] = round(avg_queue, 1)

    if avg_queue > 10:
        queue_penalty = min(30.0, (avg_queue - 10) * 2)
        score -= queue_penalty
        evidence["queue_penalty"] = round(queue_penalty, 1)

    # RSSI
    rssi_values = [r.get("wifi_rssi") for r in recent if r.get("wifi_rssi") is not None]
    if rssi_values:
        avg_rssi = sum(rssi_values) / len(rssi_values)
        evidence["avg_rssi"] = round(avg_rssi, 1)
        if avg_rssi < -80:
            rssi_penalty = min(25.0, (abs(avg_rssi) - 80) * 1.5)
            score -= rssi_penalty
            evidence["rssi_penalty"] = round(rssi_penalty, 1)

    # Active performance anomalies
    perf_anomalies = [
        a for a in active_anomalies if a.get("category") == "performance"
    ]
    score -= min(20.0, len(perf_anomalies) * 10.0)
    evidence["performance_anomaly_count"] = len(perf_anomalies)

    return max(0.0, min(100.0, score)), evidence


def _security_score(
    node: dict[str, Any],
    active_anomalies: list[dict[str, Any]],
) -> tuple[float, dict[str, Any]]:
    """
    Factors: OTA support, firmware version presence, active security anomalies.
    Phase 2 baseline — HMAC adoption deferred to Phase 3.
    """
    score = 100.0
    evidence: dict[str, Any] = {}

    # No OTA support is a mild concern (patch delivery)
    if not node.get("supports_ota"):
        score -= 10.0
        evidence["ota_penalty"] = 10

    # Missing firmware version
    fw = node.get("firmware_version", "")
    if not fw or fw == "unknown":
        score -= 5.0
        evidence["firmware_version_missing"] = True

    # Active security anomalies carry heavy weight
    sec_anomalies = [
        a for a in active_anomalies if a.get("category") == "security"
    ]
    if sec_anomalies:
        sec_penalty = min(60.0, len(sec_anomalies) * 30.0)
        score -= sec_penalty
        evidence["security_anomaly_count"] = len(sec_anomalies)
        evidence["security_penalty"] = sec_penalty

    return max(0.0, min(100.0, score)), evidence


def _maintainability_score(node: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """
    Factors: OTA support, device UID presence, hardware model known.
    """
    score = 100.0
    evidence: dict[str, Any] = {}

    if not node.get("supports_ota"):
        score -= 20.0
        evidence["no_ota"] = True

    if not node.get("device_uid") or node.get("device_uid") == "":
        score -= 15.0
        evidence["no_device_uid"] = True

    hw = node.get("hardware_model", "")
    if not hw or hw == "unknown":
        score -= 10.0
        evidence["unknown_hardware"] = True

    return max(0.0, min(100.0, score)), evidence


def _responsiveness_score(
    node: dict[str, Any],
    heartbeats: list[dict[str, Any]],
) -> tuple[float, dict[str, Any]]:
    """
    Factors: recency of last_seen, heartbeat freshness.
    """
    evidence: dict[str, Any] = {}
    last_seen_str = node.get("last_seen_utc") or node.get("last_seen")
    if not last_seen_str:
        return 0.0, {"reason": "never_seen"}

    try:
        last_seen = datetime.fromisoformat(
            last_seen_str.replace("Z", "+00:00")
        )
        age_sec = (datetime.now(timezone.utc) - last_seen).total_seconds()
        evidence["last_seen_age_sec"] = int(age_sec)
    except ValueError:
        return 50.0, {"reason": "unparseable_timestamp"}

    offline_after = int(node.get("offline_after_sec") or 180)

    if age_sec <= offline_after:
        score = 100.0 - (age_sec / offline_after * 30.0)  # up to -30 as it ages
    else:
        score = max(0.0, 30.0 - ((age_sec - offline_after) / offline_after * 30.0))

    return max(0.0, min(100.0, score)), evidence


# ----------------------------------------------------------------
#  Node scorer
# ----------------------------------------------------------------

async def compute_node_score(
    db_path: str, node_id: str, node: dict[str, Any]
) -> HealthScoreRecord:
    """
    Compute and persist a health score for a single node.
    Returns the HealthScoreRecord (also persisted to DB).
    """
    heartbeats_raw = await get_recent_heartbeats(db_path, node_id, limit=10)
    hb_dicts = [
        {
            "queue_depth":     h.queue_depth,
            "wifi_rssi":       h.wifi_rssi,
            "free_heap_bytes": h.free_heap_bytes,
            "battery_pct":     h.battery_pct,
            "status":          h.status,
        }
        for h in heartbeats_raw
    ]

    active_anomalies = await get_anomalies(
        db_path, status="active", node_id=node_id, limit=50
    )

    rel_score, rel_ev   = _reliability_score(hb_dicts, active_anomalies, node)
    perf_score, perf_ev = _performance_score(hb_dicts, active_anomalies)
    sec_score, sec_ev   = _security_score(node, active_anomalies)
    maint_score, maint_ev = _maintainability_score(node)
    resp_score, resp_ev = _responsiveness_score(node, hb_dicts)

    health = (
        rel_score   * _WEIGHTS["reliability"]
        + perf_score  * _WEIGHTS["performance"]
        + sec_score   * _WEIGHTS["security"]
        + maint_score * _WEIGHTS["maintainability"]
        + resp_score  * _WEIGHTS["responsiveness"]
    )

    record = HealthScoreRecord(
        scope_type=ScopeType.NODE,
        scope_id=node_id,
        health_score=round(health, 2),
        reliability_score=round(rel_score, 2),
        security_score=round(sec_score, 2),
        performance_score=round(perf_score, 2),
        maintainability_score=round(maint_score, 2),
        responsiveness_score=round(resp_score, 2),
        evidence_json={
            "reliability":     rel_ev,
            "performance":     perf_ev,
            "security":        sec_ev,
            "maintainability": maint_ev,
            "responsiveness":  resp_ev,
        },
    )
    await persist_health_score(db_path, record)
    return record


async def compute_fleet_score(db_path: str) -> HealthScoreRecord:
    """
    Compute fleet-wide score as weighted average of all node scores.
    Weights critical anomaly penalties on top.
    """
    node_scores = await get_all_node_scores(db_path)
    if not node_scores:
        return HealthScoreRecord(
            scope_type=ScopeType.FLEET,
            scope_id="fleet",
            health_score=100.0,
            reliability_score=100.0,
            security_score=100.0,
            performance_score=100.0,
            maintainability_score=100.0,
            responsiveness_score=100.0,
            evidence_json={"reason": "no_nodes"},
        )

    def _avg(field: str) -> float:
        vals = [s[field] for s in node_scores if s.get(field) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    # Penalize for unresolved critical anomalies
    critical = await get_anomalies(db_path, status="active", limit=500)
    critical_count = sum(1 for a in critical if a.get("severity") == "critical")
    critical_penalty = min(20.0, critical_count * 5.0)

    health = max(0.0, _avg("health_score") - critical_penalty)

    record = HealthScoreRecord(
        scope_type=ScopeType.FLEET,
        scope_id="fleet",
        health_score=round(health, 2),
        reliability_score=round(_avg("reliability_score"), 2),
        security_score=round(_avg("security_score"), 2),
        performance_score=round(_avg("performance_score"), 2),
        maintainability_score=round(_avg("maintainability_score"), 2),
        responsiveness_score=round(_avg("responsiveness_score"), 2),
        evidence_json={
            "node_count": len(node_scores),
            "critical_anomaly_count": critical_count,
            "critical_penalty": critical_penalty,
        },
    )
    await persist_health_score(db_path, record)
    return record
