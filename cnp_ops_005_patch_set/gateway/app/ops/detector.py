from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from statistics import quantiles
from uuid import uuid4

import aiosqlite

from ..core.config import settings
from .models import AnomalyRecord
from .rules import RULES
from .summaries import refresh_heartbeat_daily_summary


class AnomalyDetector:
    """Implements A-001 through A-005."""

    async def detect_node_anomalies(
        self,
        db_path: str,
        node_id: str,
        *,
        now_ts_utc: str | None = None,
    ) -> list[AnomalyRecord]:
        now = (
            datetime.fromisoformat(now_ts_utc.replace("Z", "+00:00"))
            if now_ts_utc
            else datetime.now(timezone.utc)
        )
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            node = await (await db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,))).fetchone()
            if node is None:
                return []

            heartbeats = await (
                await db.execute(
                    "SELECT * FROM heartbeats WHERE node_id=? ORDER BY ts_utc DESC LIMIT 20",
                    (node_id,),
                )
            ).fetchall()
            command_rows = await (
                await db.execute(
                    "SELECT * FROM commands WHERE node_id=? ORDER BY issued_ts_utc DESC LIMIT 50",
                    (node_id,),
                )
            ).fetchall()
            transitions = await (
                await db.execute(
                    """
                    SELECT * FROM fleet_events
                    WHERE node_id=? AND event_type IN ('node_online', 'node_offline')
                    ORDER BY ts_utc DESC LIMIT 20
                    """,
                    (node_id,),
                )
            ).fetchall()

        await refresh_heartbeat_daily_summary(db_path)
        findings: list[AnomalyRecord] = []
        findings.extend(self._detect_queue_congestion(node, heartbeats, now))
        findings.extend(self._detect_memory_leak(node, heartbeats, now))
        findings.extend(self._detect_weak_connectivity(node, heartbeats, now))
        findings.extend(self._detect_command_lag(node, command_rows, now))
        findings.extend(self._detect_offline_flapping(node, transitions, now))
        persisted: list[AnomalyRecord] = []
        for anomaly in findings:
            inserted = await self._persist_if_new(db_path, anomaly)
            if inserted:
                persisted.append(anomaly)
        return persisted

    def _base_record(self, node_row, rule_id: str, now: datetime, *, score: float, confidence: float, evidence: dict, recommended_action: str) -> AnomalyRecord:
        metadata = json.loads(node_row["metadata_json"]) if node_row["metadata_json"] else {}
        rule = RULES[rule_id]
        return AnomalyRecord(
            anomaly_id=str(uuid4()),
            detected_ts_utc=now.isoformat().replace("+00:00", "Z"),
            node_id=node_row["node_id"],
            zone=metadata.get("zone"),
            anomaly_type=rule.anomaly_type,
            category=rule.category,
            severity=rule.severity,
            score=score,
            confidence=confidence,
            status="open",
            evidence=evidence,
            recommended_action=recommended_action,
            source_rule_id=rule_id,
        )

    def _detect_queue_congestion(self, node_row, heartbeats, now):
        rule = RULES["A-001"]
        if len(heartbeats) < rule.threshold["consecutive_hits"]:
            return []
        recent = heartbeats[: rule.threshold["consecutive_hits"]]
        if all((hb["queue_depth"] or 0) > rule.threshold["queue_depth"] for hb in recent):
            evidence = {
                "queue_depths": [hb["queue_depth"] for hb in recent],
                "threshold": rule.threshold["queue_depth"],
            }
            return [self._base_record(node_row, "A-001", now, score=72.0, confidence=0.94, evidence=evidence, recommended_action=rule.default_action)]
        return []

    def _detect_memory_leak(self, node_row, heartbeats, now):
        rule = RULES["A-002"]
        free_heap = [hb["free_heap_bytes"] for hb in reversed(heartbeats[:5]) if hb["free_heap_bytes"] is not None]
        if len(free_heap) < 3:
            return []
        declining = all(a > b for a, b in zip(free_heap[:-1], free_heap[1:]))
        avg_heap = sum(free_heap) / len(free_heap)
        if declining and free_heap[-1] < avg_heap:
            evidence = {"free_heap_bytes": free_heap, "moving_average": avg_heap}
            return [self._base_record(node_row, "A-002", now, score=68.0, confidence=0.83, evidence=evidence, recommended_action=rule.default_action)]
        return []

    def _detect_weak_connectivity(self, node_row, heartbeats, now):
        rule = RULES["A-003"]
        threshold = rule.threshold["wifi_rssi"]
        window_start = now - timedelta(seconds=rule.threshold["window_sec"])
        recent = [
            hb for hb in heartbeats
            if datetime.fromisoformat(hb["ts_utc"].replace("Z", "+00:00")) >= window_start
        ]
        if len(recent) < rule.threshold["min_samples"]:
            return []
        if all((hb["wifi_rssi"] or 0) < threshold for hb in recent[: rule.threshold["min_samples"]]):
            evidence = {"wifi_rssi": [hb["wifi_rssi"] for hb in recent[: rule.threshold["min_samples"]]], "threshold": threshold}
            return [self._base_record(node_row, "A-003", now, score=61.0, confidence=0.9, evidence=evidence, recommended_action=rule.default_action)]
        return []

    def _detect_command_lag(self, node_row, command_rows, now):
        rule = RULES["A-004"]
        latencies = []
        for row in command_rows:
            if row["completed_ts_utc"] and row["status"] in {"acked", "executed", "success"}:
                issued = datetime.fromisoformat(row["issued_ts_utc"].replace("Z", "+00:00"))
                completed = datetime.fromisoformat(row["completed_ts_utc"].replace("Z", "+00:00"))
                latencies.append((completed - issued).total_seconds() * 1000)
        if len(latencies) < rule.threshold["min_samples"]:
            return []
        sorted_latencies = sorted(latencies)
        p95 = sorted_latencies[-1] if len(sorted_latencies) < 20 else quantiles(sorted_latencies, n=100)[94]
        if p95 > settings.ops_command_lag_threshold_ms:
            evidence = {"p95_ms": p95, "sample_count": len(latencies)}
            return [self._base_record(node_row, "A-004", now, score=66.0, confidence=0.88, evidence=evidence, recommended_action=rule.default_action)]
        return []

    def _detect_offline_flapping(self, node_row, transitions, now):
        rule = RULES["A-005"]
        window_start = now - timedelta(seconds=rule.threshold["window_sec"])
        recent = [
            row for row in transitions
            if datetime.fromisoformat(row["ts_utc"].replace("Z", "+00:00")) >= window_start
        ]
        if len(recent) >= rule.threshold["transitions"]:
            evidence = {"transition_count": len(recent), "window_sec": rule.threshold["window_sec"]}
            return [self._base_record(node_row, "A-005", now, score=64.0, confidence=0.86, evidence=evidence, recommended_action=rule.default_action)]
        return []

    async def _persist_if_new(self, db_path: str, anomaly: AnomalyRecord) -> bool:
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                """
                SELECT anomaly_id FROM ops_anomalies
                WHERE node_id=? AND source_rule_id=? AND status IN ('open', 'acknowledged')
                """,
                (anomaly.node_id, anomaly.source_rule_id),
            ) as cur:
                existing = await cur.fetchone()
            if existing is not None:
                return False
            await db.execute(
                """
                INSERT INTO ops_anomalies(
                    anomaly_id, detected_ts_utc, node_id, zone, anomaly_type, category,
                    severity, score, confidence, status, evidence_json,
                    recommended_action, source_rule_id, correlation_id, resolved_ts_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    anomaly.anomaly_id,
                    anomaly.detected_ts_utc,
                    anomaly.node_id,
                    anomaly.zone,
                    anomaly.anomaly_type,
                    anomaly.category,
                    anomaly.severity,
                    anomaly.score,
                    anomaly.confidence,
                    anomaly.status,
                    json.dumps(anomaly.evidence),
                    anomaly.recommended_action,
                    anomaly.source_rule_id,
                    anomaly.correlation_id,
                    anomaly.resolved_ts_utc,
                ),
            )
            await db.commit()
        return True
