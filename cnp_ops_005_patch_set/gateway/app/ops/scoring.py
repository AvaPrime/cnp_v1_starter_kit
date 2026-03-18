from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from .models import ScoreCard


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, round(value, 2)))


class ScoreCalculator:
    """Deterministic score calculator for node and fleet health."""

    async def calculate_node_score(self, db_path: str, node_id: str) -> ScoreCard:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            node = await (await db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,))).fetchone()
            if node is None:
                raise ValueError(f"Unknown node_id: {node_id}")

            recent_anomalies = await (
                await db.execute(
                    """
                    SELECT anomaly_type, severity, status
                    FROM ops_anomalies
                    WHERE node_id=? AND status IN ('open', 'acknowledged')
                    """,
                    (node_id,),
                )
            ).fetchall()
            hb_rows = await (
                await db.execute(
                    """
                    SELECT queue_depth, wifi_rssi, free_heap_bytes
                    FROM heartbeats WHERE node_id=?
                    ORDER BY ts_utc DESC LIMIT 10
                    """,
                    (node_id,),
                )
            ).fetchall()
            commands = await (
                await db.execute(
                    """
                    SELECT issued_ts_utc, completed_ts_utc, status
                    FROM commands WHERE node_id=? ORDER BY issued_ts_utc DESC LIMIT 20
                    """,
                    (node_id,),
                )
            ).fetchall()

        open_count = len(recent_anomalies)
        critical_count = sum(1 for row in recent_anomalies if row["severity"] in {"critical", "high"})
        queue_penalty = 0.0
        rssi_penalty = 0.0
        memory_penalty = 0.0

        if hb_rows:
            avg_queue = sum((row["queue_depth"] or 0) for row in hb_rows) / len(hb_rows)
            avg_rssi = sum((row["wifi_rssi"] or -70) for row in hb_rows) / len(hb_rows)
            free_heap = [row["free_heap_bytes"] for row in hb_rows if row["free_heap_bytes"] is not None]
            queue_penalty = min(25.0, avg_queue * 1.8)
            if avg_rssi < -80:
                rssi_penalty = min(20.0, abs(avg_rssi + 80) * 0.8)
            if len(free_heap) >= 3 and all(a > b for a, b in zip(free_heap[::-1][:-1], free_heap[::-1][1:])):
                memory_penalty = 10.0

        latency_penalty = 0.0
        signed_bonus = 0.0
        if commands:
            latencies = []
            for row in commands:
                if row["status"] in {"acked", "executed", "success"} and row["completed_ts_utc"]:
                    issued = datetime.fromisoformat(row["issued_ts_utc"].replace("Z", "+00:00"))
                    completed = datetime.fromisoformat(row["completed_ts_utc"].replace("Z", "+00:00"))
                    latencies.append((completed - issued).total_seconds() * 1000)
            if latencies:
                avg_latency = sum(latencies) / len(latencies)
                if avg_latency > 2000:
                    latency_penalty = min(20.0, (avg_latency - 2000) / 250)

        reliability = _clamp(100 - (open_count * 8) - (critical_count * 12) - memory_penalty)
        performance = _clamp(100 - queue_penalty - latency_penalty)
        security = _clamp(100 - (10 * sum(1 for row in recent_anomalies if row["anomaly_type"] in {"auth_failure_burst", "invalid_message_storm"})) + signed_bonus)
        maintainability = _clamp(100 - (5 * sum(1 for row in recent_anomalies if row["anomaly_type"] == "offline_flapping")))
        responsiveness = _clamp(100 - (latency_penalty + rssi_penalty))

        health = _clamp(
            (reliability * 0.35)
            + (performance * 0.25)
            + (security * 0.20)
            + (maintainability * 0.10)
            + (responsiveness * 0.10)
        )
        evidence = {
            "open_anomalies": open_count,
            "critical_anomalies": critical_count,
            "queue_penalty": queue_penalty,
            "rssi_penalty": rssi_penalty,
            "memory_penalty": memory_penalty,
            "latency_penalty": latency_penalty,
        }
        return ScoreCard(
            scope_type="node",
            scope_id=node_id,
            ts_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            health_score=health,
            reliability_score=reliability,
            security_score=security,
            performance_score=performance,
            maintainability_score=maintainability,
            responsiveness_score=responsiveness,
            evidence=evidence,
        )

    async def calculate_fleet_score(self, db_path: str) -> ScoreCard:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            nodes = await (await db.execute("SELECT node_id FROM nodes")).fetchall()
            anomalies = await (
                await db.execute(
                    "SELECT severity, status FROM ops_anomalies WHERE status IN ('open', 'acknowledged')"
                )
            ).fetchall()

        if not nodes:
            base = ScoreCard(
                scope_type="fleet",
                scope_id="fleet",
                ts_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                health_score=100.0,
                reliability_score=100.0,
                security_score=100.0,
                performance_score=100.0,
                maintainability_score=100.0,
                responsiveness_score=100.0,
                evidence={"reason": "no_nodes"},
            )
            return base

        node_scores = [await self.calculate_node_score(db_path, row["node_id"]) for row in nodes]
        avg = lambda attr: _clamp(sum(getattr(score, attr) for score in node_scores) / len(node_scores))
        unresolved_critical = sum(1 for row in anomalies if row["severity"] in {"critical", "high"})
        health = _clamp(avg("health_score") - (unresolved_critical * 3))
        return ScoreCard(
            scope_type="fleet",
            scope_id="fleet",
            ts_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            health_score=health,
            reliability_score=avg("reliability_score"),
            security_score=avg("security_score"),
            performance_score=avg("performance_score"),
            maintainability_score=avg("maintainability_score"),
            responsiveness_score=avg("responsiveness_score"),
            evidence={
                "node_count": len(node_scores),
                "unresolved_critical_anomalies": unresolved_critical,
            },
        )

    async def persist_score(self, db_path: str, score: ScoreCard) -> None:
        evidence_json = json.dumps(score.evidence)
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                INSERT INTO ops_health_scores(
                    score_id, ts_utc, scope_type, scope_id, health_score, reliability_score,
                    security_score, performance_score, maintainability_score, responsiveness_score,
                    evidence_json
                ) VALUES (hex(randomblob(16)), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    score.ts_utc,
                    score.scope_type,
                    score.scope_id,
                    score.health_score,
                    score.reliability_score,
                    score.security_score,
                    score.performance_score,
                    score.maintainability_score,
                    score.responsiveness_score,
                    evidence_json,
                ),
            )
            await db.commit()
