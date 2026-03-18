"""
CNP-OPS-004 — Operational Intelligence Layer

Public interface for the ops subsystem.
Import OpsServices and wire into main.py lifespan.
"""
from __future__ import annotations

import asyncio
import logging

from .detector import AnomalyQueue, DetectorService
from .healer import HealerService
from .summaries import SummaryService

log = logging.getLogger("cnp.ops")


class OpsServices:
    """
    Container that owns all ops background services and
    exposes the detector for injection into the MQTT bridge.

    Usage in main.py:

        ops = OpsServices(db_path=settings.gateway_db_path)

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await init_db(settings.gateway_db_path)
            await init_ops_db(settings.gateway_db_path)
            await bridge.start()
            ops.wire_bridge(bridge)        # inject bridge into healer
            bridge.set_ops_detector(ops.detector)  # inject detector into bridge
            tasks = await ops.start()
            ...
            yield
            ...
            await ops.stop(tasks)
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.queue = AnomalyQueue(maxsize=512)
        self.detector = DetectorService(db_path=db_path, anomaly_queue=self.queue)
        self._healer: HealerService | None = None
        self._summary: SummaryService | None = None

    def wire_bridge(self, bridge: object) -> None:
        """Inject MQTT bridge into the healer after bridge is started."""
        self._healer = HealerService(
            db_path=self.db_path,
            anomaly_queue=self.queue,
            mqtt_bridge=bridge,
        )

    async def start(self) -> list[asyncio.Task]:
        """Start all background tasks. Returns task list for cancellation."""
        if self._healer is None:
            log.warning("HealerService not wired — call wire_bridge() first")
            self._healer = HealerService(
                db_path=self.db_path,
                anomaly_queue=self.queue,
                mqtt_bridge=None,
            )
        self._summary = SummaryService(db_path=self.db_path)
        tasks = [
            asyncio.create_task(self._healer.run(), name="ops-healer"),
            asyncio.create_task(self._summary.run(), name="ops-summaries"),
        ]
        log.info("OpsServices started (%d background tasks)", len(tasks))
        return tasks

    @staticmethod
    async def stop(tasks: list[asyncio.Task]) -> None:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        log.info("OpsServices stopped")


async def init_ops_db(db_path: str) -> None:
    """
    Apply the ops schema migration (002_ops_tables.sql).
    Called from main.py lifespan after init_db().
    """
    from pathlib import Path
    import aiosqlite

    migration = Path(__file__).parents[3] / "migrations" / "002_ops_tables.sql"
    if not migration.exists():
        log.error("Ops migration not found at %s", migration)
        return
    sql = migration.read_text(encoding="utf-8")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(sql)
        await db.commit()
    log.info("Ops DB schema applied from %s", migration)
