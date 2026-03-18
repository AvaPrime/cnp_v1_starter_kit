"""
CNP EPIC-01 — Updated main.py
Wires: rate limit middleware, migration runner, ops services stub.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .core.config import settings
from .core.db import init_db
from .core.mqtt_client import GatewayMqttBridge
from .core.rate_limit import RateLimitMiddleware
from .core.registry import mark_offline_nodes

log = logging.getLogger("cnp.main")

bridge = GatewayMqttBridge(settings.gateway_db_path)


async def _apply_migrations(db_path: str) -> None:
    """Apply all SQL migration files in order."""
    import aiosqlite
    migrations_dir = Path(__file__).parents[3] / "migrations"
    if not migrations_dir.exists():
        log.warning("Migrations directory not found at %s", migrations_dir)
        return
    for migration in sorted(migrations_dir.glob("*.sql")):
        log.info("Applying migration: %s", migration.name)
        sql = migration.read_text(encoding="utf-8")
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(sql)
            await db.commit()


async def _offline_watcher() -> None:
    while True:
        try:
            count = await mark_offline_nodes(
                settings.gateway_db_path, settings.offline_after_seconds
            )
            if count > 0:
                log.info("offline_watcher marked %d node(s) offline", count)
        except Exception as exc:
            log.error("offline_watcher error: %s", exc)
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Init base schema then apply migrations
    await init_db(settings.gateway_db_path)
    await _apply_migrations(settings.gateway_db_path)

    await bridge.start()

    watcher = asyncio.create_task(_offline_watcher(), name="offline-watcher")
    try:
        yield
    finally:
        watcher.cancel()
        await bridge.stop()
        try:
            await watcher
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="CNP v1 Gateway",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS — restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# P1-04 Rate limit middleware
app.add_middleware(RateLimitMiddleware)

app.include_router(router, prefix="/api")
