from __future__ import annotations

from .models import AnomalyRecord, ReflexAction
from .reflex import ReflexEngine


class AutoHealingExecutor:
    """Thin orchestration wrapper around the reflex engine."""

    def __init__(self, reflex_engine: ReflexEngine | None = None) -> None:
        self.reflex_engine = reflex_engine or ReflexEngine()

    async def heal(self, db_path: str, anomaly: AnomalyRecord) -> ReflexAction:
        action = await self.reflex_engine.plan(anomaly)
        return await self.reflex_engine.execute(db_path, action)
