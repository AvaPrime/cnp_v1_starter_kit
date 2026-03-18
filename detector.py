"""
CNP-OPS-004 — Anomaly Detection Engine.

Architecture:
  - Each heartbeat received by the MQTT bridge calls
    `detector.on_heartbeat(envelope)`.
  - The detector maintains per-node rolling windows in memory
    (bounded deques — no DB reads on hot path).
  - Rules evaluate against those windows.
  - Anomalies are written to DB and enqueued to the reflex
    engine's asyncio.Queue for immediate processing.
  - Suppression is checked against DB before raising.

Rules implemented here (Phase O2):
  A-001  Queue Congestion
  A-002  Memory Leak Suspected
  A-003  Weak Connectivity
  A-005  Offline Flapping
  A-010  Fleet Hotspot (zone-level, triggered after node anomalies)

Rules deferred (Phase O3+ — require board Phase 3 signals):
  A-004  Command Lag       (needs P3-05 + P4-05)
  A-006  Auth Failure Burst (needs P1-07 event log)
  A-007  Invalid Message Storm (needs P1-05 event log)
  A-008  Dead-Letter Growth   (needs P3-06)
  A-009  Duplicate Spike      (needs P3-04)
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import (
    count_active_anomalies_by_type,
    get_recent_heartbeats,
    is_suppressed,
    persist_anomaly,
    upsert_rule_state,
)
from .models import (
    AnomalyCategory,
    AnomalyRecord,
    AnomalySeverity,
    AnomalyStatus,
    HeartbeatSnapshot,
    RuleStateRecord,
    ScopeType,
)
from .rules import RULES, get_rule

log = logging.getLogger("cnp.ops.detector")

# Maximum heartbeats to retain in memory per node
_WINDOW_SIZE = 20


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AnomalyQueue:
    """Thin wrapper around asyncio.Queue for type-safety."""

    def __init__(self, maxsize: int = 256) -> None:
        self._q: asyncio.Queue[AnomalyRecord] = asyncio.Queue(maxsize=maxsize)

    async def put(self, anomaly: AnomalyRecord) -> None:
        try:
            self._q.put_nowait(anomaly)
        except asyncio.QueueFull:
            log.warning(
                "Anomaly queue full — dropping anomaly %s for node %s",
                anomaly.anomaly_type,
                anomaly.node_id,
            )

    async def get(self) -> AnomalyRecord:
        return await self._q.get()

    def task_done(self) -> None:
        self._q.task_done()

    def qsize(self) -> int:
        return self._q.qsize()


class DetectorService:
    """
    Stateful anomaly detector.

    Call `on_heartbeat(envelope)` from the MQTT bridge after
    persisting the heartbeat. Call `on_node_offline(node_id)`
    from the offline watcher on each transition.
    """

    def __init__(self, db_path: str, anomaly_queue: AnomalyQueue) -> None:
        self._db_path = db_path
        self._queue = anomaly_queue
        # node_id → deque[HeartbeatSnapshot], oldest-first
        self._windows: dict[str, deque[HeartbeatSnapshot]] = {}
        # node_id → list of (ts, direction) for flap tracking
        self._flap_log: dict[str, deque[tuple[datetime, str]]] = {}

    # ----------------------------------------------------------------
    #  Public API
    # ----------------------------------------------------------------

    async def on_heartbeat(self, envelope: dict[str, Any]) -> None:
        """
        Entry point called by MQTT bridge after update_heartbeat().
        Non-blocking — all heavy work is async.
        """
        node_id = envelope.get("node_id", "")
        payload = envelope.get("payload", {})

        snap = HeartbeatSnapshot(
            node_id=node_id,
            ts_utc=envelope.get("ts_utc", _now_utc()),
            free_heap_bytes=payload.get("free_heap_bytes"),
            wifi_rssi=payload.get("wifi_rssi"),
            queue_depth=int(payload.get("queue_depth") or 0),
            battery_pct=payload.get("battery_pct"),
            status=payload.get("status", "online"),
            seq=payload.get("seq"),
        )

        self._append_window(node_id, snap)
        window = list(self._windows[node_id])

        await self._check_a001_queue_congestion(node_id, window)
        await self._check_a002_memory_leak(node_id, window)
        await self._check_a003_weak_connectivity(node_id, window)

    async def on_node_offline(self, node_id: str, zone: str | None = None) -> None:
        """
        Called by offline_watcher on every online→offline transition.
        Feeds A-005 (flap detection) and A-010 (zone hotspot).
        """
        now = datetime.now(timezone.utc)
        if node_id not in self._flap_log:
            self._flap_log[node_id] = deque(maxlen=20)
        self._flap_log[node_id].append((now, "offline"))
        await self._check_a005_offline_flapping(node_id, zone)
        if zone:
            await self._check_a010_fleet_hotspot(zone)

    async def on_node_online(self, node_id: str) -> None:
        """Called when a node transitions back to online."""
        now = datetime.now(timezone.utc)
        if node_id not in self._flap_log:
            self._flap_log[node_id] = deque(maxlen=20)
        self._flap_log[node_id].append((now, "online"))

    # ----------------------------------------------------------------
    #  Window management
    # ----------------------------------------------------------------

    def _append_window(self, node_id: str, snap: HeartbeatSnapshot) -> None:
        if node_id not in self._windows:
            self._windows[node_id] = deque(maxlen=_WINDOW_SIZE)
        self._windows[node_id].append(snap)

    def get_window(self, node_id: str) -> list[HeartbeatSnapshot]:
        """Exposed for testing."""
        return list(self._windows.get(node_id, []))

    # ----------------------------------------------------------------
    #  A-001  Queue Congestion
    # ----------------------------------------------------------------

    async def _check_a001_queue_congestion(
        self, node_id: str, window: list[HeartbeatSnapshot]
    ) -> None:
        rule = get_rule("A-001")
        if not rule:
            return

        threshold = 10
        required_hits = rule.consecutive_hits

        if len(window) < required_hits:
            return

        recent = window[-required_hits:]
        all_congested = all(s.queue_depth > threshold for s in recent)

        if not all_congested:
            return

        if await is_suppressed(self._db_path, "A-001", "node", node_id):
            return

        depths = [s.queue_depth for s in recent]
        anomaly = AnomalyRecord(
            node_id=node_id,
            anomaly_type=rule.anomaly_type,
            category=AnomalyCategory.PERFORMANCE,
            severity=AnomalySeverity.WARNING,
            score=min(1.0, max(depths) / 50.0),
            confidence=rule.confidence,
            source_rule_id="A-001",
            evidence_json={
                "queue_depths": depths,
                "threshold": threshold,
                "consecutive_hits": required_hits,
            },
            recommended_action="Increase telemetry interval or check broker connectivity.",
        )
        await self._raise_anomaly(anomaly, rule.suppress_for_sec)

    # ----------------------------------------------------------------
    #  A-002  Memory Leak Suspected
    # ----------------------------------------------------------------

    async def _check_a002_memory_leak(
        self, node_id: str, window: list[HeartbeatSnapshot]
    ) -> None:
        rule = get_rule("A-002")
        if not rule:
            return

        required = 3
        if len(window) < required:
            return

        recent = window[-required:]
        heaps = [s.free_heap_bytes for s in recent if s.free_heap_bytes is not None]

        if len(heaps) < required:
            return  # insufficient data

        # Strict monotone decline + no recovery
        is_declining = all(heaps[i] > heaps[i + 1] for i in range(len(heaps) - 1))
        if not is_declining:
            return

        # Only fire if the decline is meaningful (>5% drop across window)
        pct_drop = (heaps[0] - heaps[-1]) / heaps[0] if heaps[0] > 0 else 0
        if pct_drop < 0.05:
            return

        if await is_suppressed(self._db_path, "A-002", "node", node_id):
            return

        anomaly = AnomalyRecord(
            node_id=node_id,
            anomaly_type=rule.anomaly_type,
            category=AnomalyCategory.RELIABILITY,
            severity=AnomalySeverity.WARNING,
            score=min(1.0, pct_drop * 5),  # 20% drop → score 1.0
            confidence=rule.confidence,
            source_rule_id="A-002",
            evidence_json={
                "free_heap_bytes_series": heaps,
                "pct_drop": round(pct_drop * 100, 2),
            },
            recommended_action=(
                "Monitor for continued decline. "
                "If trend persists across 5 heartbeats, schedule maintenance reboot."
            ),
        )
        await self._raise_anomaly(anomaly, rule.suppress_for_sec)

    # ----------------------------------------------------------------
    #  A-003  Weak Connectivity
    # ----------------------------------------------------------------

    async def _check_a003_weak_connectivity(
        self, node_id: str, window: list[HeartbeatSnapshot]
    ) -> None:
        rule = get_rule("A-003")
        if not rule:
            return

        required_hits = rule.consecutive_hits
        rssi_threshold = -80

        if len(window) < required_hits:
            return

        recent = window[-required_hits:]
        rssi_values = [s.wifi_rssi for s in recent if s.wifi_rssi is not None]

        if len(rssi_values) < required_hits:
            return

        all_weak = all(r < rssi_threshold for r in rssi_values)
        if not all_weak:
            return

        if await is_suppressed(self._db_path, "A-003", "node", node_id):
            return

        avg_rssi = sum(rssi_values) / len(rssi_values)
        # Normalize: -80 = score 0.3, -95 = score 1.0
        score = min(1.0, max(0.1, (abs(avg_rssi) - 80) / 15))

        anomaly = AnomalyRecord(
            node_id=node_id,
            anomaly_type=rule.anomaly_type,
            category=AnomalyCategory.CONNECTIVITY,
            severity=AnomalySeverity.WARNING,
            score=score,
            confidence=rule.confidence,
            source_rule_id="A-003",
            evidence_json={
                "rssi_values": rssi_values,
                "avg_rssi": round(avg_rssi, 1),
                "threshold": rssi_threshold,
            },
            recommended_action=(
                "Check node placement relative to AP. "
                "Telemetry rate reduced automatically via config_update."
            ),
        )
        await self._raise_anomaly(anomaly, rule.suppress_for_sec)

    # ----------------------------------------------------------------
    #  A-005  Offline Flapping
    # ----------------------------------------------------------------

    async def _check_a005_offline_flapping(
        self, node_id: str, zone: str | None
    ) -> None:
        rule = get_rule("A-005")
        if not rule:
            return

        flap_threshold = 3
        window_sec = 600

        transitions = self._flap_log.get(node_id, deque())
        if not transitions:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_sec)
        recent_transitions = [t for t, _ in transitions if t >= cutoff]

        if len(recent_transitions) < flap_threshold:
            return

        if await is_suppressed(self._db_path, "A-005", "node", node_id):
            return

        anomaly = AnomalyRecord(
            node_id=node_id,
            zone=zone,
            anomaly_type=rule.anomaly_type,
            category=AnomalyCategory.RELIABILITY,
            severity=AnomalySeverity.ERROR,
            score=min(1.0, len(recent_transitions) / 10.0),
            confidence=rule.confidence,
            source_rule_id="A-005",
            evidence_json={
                "transition_count": len(recent_transitions),
                "window_sec": window_sec,
                "threshold": flap_threshold,
            },
            recommended_action=(
                "Inspect WiFi stability near node. "
                "offline_after_sec will be increased automatically."
            ),
        )
        await self._raise_anomaly(anomaly, rule.suppress_for_sec)

    # ----------------------------------------------------------------
    #  A-010  Fleet Hotspot (zone-level)
    # ----------------------------------------------------------------

    async def _check_a010_fleet_hotspot(self, zone: str) -> None:
        rule = get_rule("A-010")
        if not rule:
            return

        if await is_suppressed(self._db_path, "A-010", "zone", zone):
            return

        target_types = ["queue_congestion", "weak_connectivity", "offline_flapping"]
        window_sec = 300
        min_nodes = 3
        coverage_threshold = 0.5

        type_counts = await count_active_anomalies_by_type(
            self._db_path, target_types, zone, window_sec
        )

        total_affected = sum(type_counts.values())
        if total_affected < min_nodes:
            return

        # Require at least 2 distinct anomaly types for zone-level signal
        active_types = [t for t, c in type_counts.items() if c > 0]
        if len(active_types) < 2:
            return

        anomaly = AnomalyRecord(
            node_id=None,
            zone=zone,
            anomaly_type=rule.anomaly_type,
            category=AnomalyCategory.FLEET,
            severity=AnomalySeverity.ERROR,
            score=min(1.0, total_affected / 10.0),
            confidence=rule.confidence,
            source_rule_id="A-010",
            evidence_json={
                "zone": zone,
                "affected_node_counts_by_type": type_counts,
                "total_affected": total_affected,
                "active_anomaly_types": active_types,
            },
            recommended_action=(
                "Inspect zone-wide network infrastructure. "
                "Non-critical zone automation paused automatically."
            ),
        )
        await self._raise_anomaly(anomaly, rule.suppress_for_sec)

    # ----------------------------------------------------------------
    #  Internal helpers
    # ----------------------------------------------------------------

    async def _raise_anomaly(
        self, anomaly: AnomalyRecord, suppress_for_sec: int
    ) -> None:
        """Persist, enqueue, and set suppression window."""
        anomaly.status = AnomalyStatus.ACTIVE
        await persist_anomaly(self._db_path, anomaly)
        await self._queue.put(anomaly)

        # Set suppression window
        until = datetime.now(timezone.utc) + timedelta(seconds=suppress_for_sec)
        scope_type = "zone" if anomaly.zone and not anomaly.node_id else "node"
        scope_id = anomaly.zone if scope_type == "zone" else (anomaly.node_id or "")
        state = RuleStateRecord(
            rule_id=anomaly.source_rule_id,
            scope_type=ScopeType(scope_type),
            scope_id=scope_id,
            last_triggered_ts_utc=_now_utc(),
            suppression_until_ts_utc=until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            consecutive_hits=1,
            last_anomaly_id=anomaly.anomaly_id,
        )
        await upsert_rule_state(self._db_path, state)

        log.info(
            "[ANOMALY] %s raised for %s %s (severity=%s score=%.2f)",
            anomaly.anomaly_type,
            scope_type,
            scope_id,
            anomaly.severity.value,
            anomaly.score,
        )
