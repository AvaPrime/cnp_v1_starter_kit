from __future__ import annotations

import aiosqlite

from .detector import AnomalyDetector
from .healer import AutoHealingExecutor
from .scoring import ScoreCalculator


class OpsService:
    def __init__(
        self,
        detector: AnomalyDetector | None = None,
        healer: AutoHealingExecutor | None = None,
        scoring: ScoreCalculator | None = None,
    ) -> None:
        self.detector = detector or AnomalyDetector()
        self.healer = healer or AutoHealingExecutor()
        self.scoring = scoring or ScoreCalculator()

    async def analyze_node(self, db_path: str, node_id: str, *, auto_heal: bool = False):
        anomalies = await self.detector.detect_node_anomalies(db_path, node_id)
        actions = []
        if auto_heal:
            for anomaly in anomalies:
                action = await self.healer.heal(db_path, anomaly)
                actions.append(action)
        score = await self.scoring.calculate_node_score(db_path, node_id)
        await self.scoring.persist_score(db_path, score)
        return anomalies, actions, score

    async def list_anomalies(self, db_path: str):
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute("SELECT * FROM ops_anomalies ORDER BY detected_ts_utc DESC")).fetchall()
        return [dict(row) for row in rows]
