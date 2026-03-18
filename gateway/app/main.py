from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.routes import router
from .api.compat import router as compat_router
from .api.admin import router as admin_router
from .core.config import settings
from .core.db import init_db
from .core.mqtt_client import GatewayMqttBridge
from .core.registry import mark_offline_nodes
from .core.rate_limit import RateLimitMiddleware

bridge = GatewayMqttBridge(settings.gateway_db_path)


async def offline_watcher() -> None:
    while True:
        await mark_offline_nodes(settings.gateway_db_path, settings.offline_after_seconds)
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(settings.gateway_db_path)
    await bridge.start()
    task = asyncio.create_task(offline_watcher())
    try:
        yield
    finally:
        task.cancel()
        await bridge.stop()


app = FastAPI(title="CNP v1 Gateway", version="0.2.0", lifespan=lifespan)
app.add_middleware(RateLimitMiddleware)
app.include_router(router, prefix="/api")
app.include_router(compat_router, prefix="/v1/compat")
app.include_router(admin_router, prefix="/api")
