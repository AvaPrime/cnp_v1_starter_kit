from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

from .api.routes import router as api_router
from .core.config import settings
from .core.db import apply_sql_file, init_db
from .core.mqtt_client import GatewayMqttBridge
from .core.registry import mark_offline_nodes
from .ops.api import router as ops_router

OPS_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "001_ops_tables.sql"


def create_app(db_path: str | None = None, enable_bridge: bool | None = None) -> FastAPI:
    app = FastAPI(title="CNP v1 Gateway", version="0.2.0")
    app.include_router(api_router, prefix="/api")
    app.include_router(ops_router, prefix="/api/ops")
    app.state.db_path = db_path or settings.gateway_db_path
    app.state.enable_bridge = settings.enable_mqtt_bridge if enable_bridge is None else enable_bridge
    app.state.bridge = GatewayMqttBridge(app.state.db_path)

    async def offline_watcher() -> None:
        while True:
            await mark_offline_nodes(app.state.db_path, settings.offline_after_seconds)
            await asyncio.sleep(15)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await init_db(app.state.db_path)
        await apply_sql_file(app.state.db_path, str(OPS_MIGRATION))
        if app.state.enable_bridge:
            await app.state.bridge.start()
        task = asyncio.create_task(offline_watcher())
        try:
            yield
        finally:
            task.cancel()
            if app.state.enable_bridge:
                await app.state.bridge.stop()

    app.router.lifespan_context = lifespan
    return app


app = create_app()
