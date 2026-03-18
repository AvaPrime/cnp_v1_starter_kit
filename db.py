"""
CNP-OPS-004 — Database helpers for the ops layer.

All functions are async and use aiosqlite. They mirror the
pattern established in gateway/app/core/storage.py.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from .models import (
    AnomalyRecord,
    AnomalyStatus,
    HeartbeatDailySummaryRecord,
    HeartbeatSnapshot,
    HealthScoreRecord,
    ReflexActionRecord,
    ReflexExecutionStatus,
    RuleStateRecord,
    ScopeType,
)

log = logging.getLogger("cnp.ops.db")


# ----------------------------------------------------------------
#  Anomalies
# ----------------------------------------------------------------

async def persist_anomaly(db_path: str, anomaly: AnomalyRecord) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO ops_anomalies (
                anomaly_id, detected_ts_utc, node_id, zone,
                anomaly_type, category, severity, score, confidence,
                status, evidence_json, recommended_action,
                source_rule_id, correlation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                anomaly.anomaly_id,
                anomaly.detected_ts_utc,
                anomaly.node_id,
                anomaly.zone,
                anomaly.anomaly_type,
                anomaly.category.value,
                anomaly.severity.value,
                anomaly.score,
                anomaly.confidence,
                anomaly.status.value,
                json.dumps(anomaly.evidence_json),
                anomaly.recommended_action,
                anomaly.source_rule_id,
                anomaly.correlation_id,
            ),
        )
        await db.commit()


async def update_anomaly_status(
    db_path: str,
    anomaly_id: str,
    status: AnomalyStatus,
    acknowledged_by: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with aiosqlite.connect(db_path) as db:
        if status == AnomalyStatus.RESOLVED:
            await db.execute(
                "UPDATE ops_anomalies SET status=?, resolved_ts_utc=? WHERE anomaly_id=?",
                (status.value, now, anomaly_id),
            )
        elif status == AnomalyStatus.ACKNOWLEDGED:
            await db.execute(
                """UPDATE ops_anomalies
                   SET status=?, acknowledged_by=?, acknowledged_ts_utc=?
                   WHERE anomaly_id=?""",
                (status.value, acknowledged_by, now, anomaly_id),
            )
        else:
            await db.execute(
                "UPDATE ops_anomalies SET status=? WHERE anomaly_id=?",
                (status.value, anomaly_id),
            )
        await db.commit()


async def get_anomalies(
    db_path: str,
    status: str | None = None,
    node_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if node_id:
        clauses.append("node_id = ?")
        params.append(node_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT * FROM ops_anomalies {where} ORDER BY detected_ts_utc DESC LIMIT ?",
            params,
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_anomaly(db_path: str, anomaly_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM ops_anomalies WHERE anomaly_id = ?", (anomaly_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def count_active_anomalies_by_type(
    db_path: str, anomaly_types: list[str], zone: str, window_sec: int
) -> dict[str, int]:
    """Used by A-010 fleet hotspot detection."""
    cutoff = datetime.now(timezone.utc)
    from datetime import timedelta
    cutoff = (cutoff - timedelta(seconds=window_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
    placeholders = ",".join("?" * len(anomaly_types))
    results: dict[str, int] = {}
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            f"""
            SELECT anomaly_type, COUNT(DISTINCT node_id) as node_count
            FROM ops_anomalies
            WHERE zone = ?
              AND anomaly_type IN ({placeholders})
              AND status IN ('detected','active')
              AND detected_ts_utc >= ?
            GROUP BY anomaly_type
            """,
            [zone] + anomaly_types + [cutoff],
        ) as cur:
            async for row in cur:
                results[row[0]] = row[1]
    return results


# ----------------------------------------------------------------
#  Reflex actions
# ----------------------------------------------------------------

async def persist_reflex_action(db_path: str, action: ReflexActionRecord) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO ops_reflex_actions (
                action_id, anomaly_id, issued_ts_utc, node_id,
                action_type, action_payload_json, safety_level,
                execution_status, safe_mode, requires_human
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action.action_id,
                action.anomaly_id,
                action.issued_ts_utc,
                action.node_id,
                action.action_type.value,
                json.dumps(action.action_payload_json),
                int(action.safety_level),
                action.execution_status.value,
                int(action.safe_mode),
                int(action.requires_human),
            ),
        )
        await db.commit()


async def update_reflex_status(
    db_path: str,
    action_id: str,
    status: ReflexExecutionStatus,
    result: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """UPDATE ops_reflex_actions
               SET execution_status=?, result_json=?, completed_ts_utc=?
               WHERE action_id=?""",
            (status.value, json.dumps(result or {}), now, action_id),
        )
        await db.commit()


# ----------------------------------------------------------------
#  Rule state
# ----------------------------------------------------------------

async def get_rule_state(
    db_path: str, rule_id: str, scope_type: str, scope_id: str
) -> RuleStateRecord:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM ops_rule_state
               WHERE rule_id=? AND scope_type=? AND scope_id=?""",
            (rule_id, scope_type, scope_id),
        ) as cur:
            row = await cur.fetchone()
    if row:
        return RuleStateRecord(**dict(row))
    return RuleStateRecord(
        rule_id=rule_id,
        scope_type=ScopeType(scope_type),
        scope_id=scope_id,
    )


async def upsert_rule_state(db_path: str, state: RuleStateRecord) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO ops_rule_state (
                rule_id, scope_type, scope_id, last_triggered_ts_utc,
                suppression_until_ts_utc, consecutive_hits,
                consecutive_recoveries, last_anomaly_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id, scope_type, scope_id) DO UPDATE SET
                last_triggered_ts_utc    = excluded.last_triggered_ts_utc,
                suppression_until_ts_utc = excluded.suppression_until_ts_utc,
                consecutive_hits         = excluded.consecutive_hits,
                consecutive_recoveries   = excluded.consecutive_recoveries,
                last_anomaly_id          = excluded.last_anomaly_id
            """,
            (
                state.rule_id,
                state.scope_type if isinstance(state.scope_type, str) else state.scope_type.value,
                state.scope_id,
                state.last_triggered_ts_utc,
                state.suppression_until_ts_utc,
                state.consecutive_hits,
                state.consecutive_recoveries,
                state.last_anomaly_id,
            ),
        )
        await db.commit()


async def is_suppressed(
    db_path: str, rule_id: str, scope_type: str, scope_id: str
) -> bool:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """SELECT 1 FROM ops_rule_state
               WHERE rule_id=? AND scope_type=? AND scope_id=?
                 AND suppression_until_ts_utc > ?""",
            (rule_id, scope_type, scope_id, now),
        ) as cur:
            return await cur.fetchone() is not None


# ----------------------------------------------------------------
#  Health scores
# ----------------------------------------------------------------

async def persist_health_score(db_path: str, score: HealthScoreRecord) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO ops_health_scores (
                score_id, ts_utc, scope_type, scope_id,
                health_score, reliability_score, security_score,
                performance_score, maintainability_score,
                responsiveness_score, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                score.score_id,
                score.ts_utc,
                score.scope_type.value,
                score.scope_id,
                score.health_score,
                score.reliability_score,
                score.security_score,
                score.performance_score,
                score.maintainability_score,
                score.responsiveness_score,
                json.dumps(score.evidence_json),
            ),
        )
        await db.commit()


async def get_latest_score(
    db_path: str, scope_type: str, scope_id: str
) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM ops_health_scores
               WHERE scope_type=? AND scope_id=?
               ORDER BY ts_utc DESC LIMIT 1""",
            (scope_type, scope_id),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def get_all_node_scores(db_path: str) -> list[dict[str, Any]]:
    """Latest score per node — used for fleet aggregation."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT s.*
            FROM ops_health_scores s
            INNER JOIN (
                SELECT scope_id, MAX(ts_utc) AS max_ts
                FROM ops_health_scores WHERE scope_type='node'
                GROUP BY scope_id
            ) latest ON s.scope_id = latest.scope_id
                     AND s.ts_utc = latest.max_ts
            WHERE s.scope_type = 'node'
            """
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ----------------------------------------------------------------
#  Heartbeat rolling window (read)
# ----------------------------------------------------------------

async def get_recent_heartbeats(
    db_path: str, node_id: str, limit: int = 10
) -> list[HeartbeatSnapshot]:
    """
    Fetch the N most recent heartbeat rows for a node.
    Maps V1 column names (battery, wifi_rssi) and V2 names
    (battery_pct, free_heap_bytes, queue_depth).
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM heartbeats
               WHERE node_id = ?
               ORDER BY received_at DESC LIMIT ?""",
            (node_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    snapshots = []
    for r in reversed(rows):  # oldest-first for window evaluation
        d = dict(r)
        snapshots.append(HeartbeatSnapshot(
            node_id=node_id,
            ts_utc=d.get("received_at", "1970-01-01T00:00:00Z"),
            free_heap_bytes=d.get("free_heap_bytes"),
            wifi_rssi=d.get("wifi_rssi"),
            queue_depth=int(d.get("queue_depth") or 0),
            battery_pct=d.get("battery_pct") or d.get("battery"),
            status=d.get("status", "online"),
        ))
    return snapshots


# ----------------------------------------------------------------
#  Daily summary upsert
# ----------------------------------------------------------------

async def upsert_daily_summary(
    db_path: str, record: HeartbeatDailySummaryRecord
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO heartbeat_daily_summary (
                node_id, day_utc,
                min_free_heap_bytes, max_free_heap_bytes, avg_free_heap_bytes,
                min_wifi_rssi, max_wifi_rssi, avg_wifi_rssi,
                min_queue_depth, max_queue_depth, avg_queue_depth,
                offline_transitions, heartbeat_count, sample_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id, day_utc) DO UPDATE SET
                min_free_heap_bytes = excluded.min_free_heap_bytes,
                max_free_heap_bytes = excluded.max_free_heap_bytes,
                avg_free_heap_bytes = excluded.avg_free_heap_bytes,
                min_wifi_rssi       = excluded.min_wifi_rssi,
                max_wifi_rssi       = excluded.max_wifi_rssi,
                avg_wifi_rssi       = excluded.avg_wifi_rssi,
                min_queue_depth     = excluded.min_queue_depth,
                max_queue_depth     = excluded.max_queue_depth,
                avg_queue_depth     = excluded.avg_queue_depth,
                offline_transitions = excluded.offline_transitions,
                heartbeat_count     = excluded.heartbeat_count,
                sample_count        = excluded.sample_count
            """,
            (
                record.node_id, record.day_utc,
                record.min_free_heap_bytes, record.max_free_heap_bytes,
                record.avg_free_heap_bytes,
                record.min_wifi_rssi, record.max_wifi_rssi,
                record.avg_wifi_rssi,
                record.min_queue_depth, record.max_queue_depth,
                record.avg_queue_depth,
                record.offline_transitions, record.heartbeat_count,
                record.sample_count,
            ),
        )
        await db.commit()
