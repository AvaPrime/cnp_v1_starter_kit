from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as StarletteHTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from datetime import datetime, timezone

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


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    def now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        err = exc.detail["error"]
        err.setdefault("timestamp", now())
        err.setdefault("path", request.url.path)
        return JSONResponse(status_code=exc.status_code, content={"error": err})
    code = "http_error"
    message = str(exc.detail)
    payload = {
        "error": {
            "code": code,
            "message": message,
            "details": {},
            "timestamp": now(),
            "path": request.url.path,
        }
    }
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    def now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = []
    for e in exc.errors():
        fields.append({"field": ".".join(str(p) for p in e.get("loc", [])), "message": e.get("msg", "")})
    payload = {
        "error": {
            "code": "request_validation_failed",
            "message": "The request is invalid",
            "details": {"fields": fields},
            "timestamp": now(),
            "path": request.url.path,
        }
    }
    return JSONResponse(status_code=400, content=payload)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description="CNP Gateway API",
        routes=app.routes,
    )
    comps = openapi_schema.setdefault("components", {}).setdefault("schemas", {})
    comps.pop("HTTPValidationError", None)
    comps.pop("ValidationError", None)
    comps["ErrorResponse"] = {
        "type": "object",
        "properties": {
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {"type": "object"},
                    "timestamp": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["code", "message", "details", "timestamp", "path"],
            }
        },
        "required": ["error"],
    }
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
