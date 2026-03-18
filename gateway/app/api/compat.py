from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request

from ..core.config import settings
from ..core.rate_limit import check_node_rate
from ..core.registry import upsert_node, update_heartbeat
from ..core.storage import insert_error, insert_event, upsert_command_result
from .routes import require_node_token
from ..models.schemas import _NODE_ID_PATTERN

log = logging.getLogger("cnp.compat")
router = APIRouter()


def _translate_envelope(raw: dict[str, Any]) -> dict[str, Any]:
    node_id = raw.get("node_id", "unknown")
    if "protocol" in raw and "protocol_version" not in raw:
        log.warning(
            "DEPRECATION_V1_KEY original_key=protocol canonical_key=protocol_version node_id=%s",
            node_id,
        )
        raw["protocol_version"] = raw.pop("protocol")
    if "timestamp" in raw and "ts_utc" not in raw:
        log.warning(
            "DEPRECATION_V1_KEY original_key=timestamp canonical_key=ts_utc node_id=%s",
            node_id,
        )
        ts = raw.pop("timestamp")
        if isinstance(ts, str) and ts.endswith("+00:00"):
            ts = ts.replace("+00:00", "Z")
        raw["ts_utc"] = ts
    if not raw.get("message_id"):
        raw["message_id"] = str(uuid.uuid4())
    if "qos" not in raw:
        raw["qos"] = 0
    payload = raw.get("payload", {})
    if "event_id" in payload:
        log.warning(
            "DEPRECATION_V1_KEY original_key=payload.event_id canonical_key=message_id node_id=%s",
            node_id,
        )
        raw["message_id"] = payload.pop("event_id")
    if "params" in payload and "arguments" not in payload:
        log.warning(
            "DEPRECATION_V1_KEY original_key=payload.params canonical_key=payload.arguments node_id=%s",
            node_id,
        )
        payload["arguments"] = payload.pop("params")
    if "error_code" in payload:
        log.warning(
            "DEPRECATION_V1_KEY original_key=payload.error_code canonical_key=payload.code node_id=%s",
            node_id,
        )
        payload["code"] = payload.pop("error_code")
        payload.setdefault("domain", "LEGACY")
        payload.setdefault("severity", "error")
        payload.setdefault("message", payload.pop("error_msg", ""))
        payload.setdefault("recoverable", True)
        payload.setdefault("diagnostics", {})
    if payload.get("battery") == -1:
        payload["battery_pct"] = None
        payload.pop("battery", None)
    elif "battery" in payload and "battery_pct" not in payload:
        payload["battery_pct"] = float(payload.pop("battery"))
    caps = payload.get("capabilities", {})
    if "power_mode" in caps:
        log.warning(
            "DEPRECATION_V1_KEY original_key=capabilities.power_mode canonical_key=capabilities.power.source node_id=%s",
            node_id,
        )
        power_mode = caps.pop("power_mode")
        caps.setdefault("power", {})["source"] = power_mode
    if raw.get("message_type") == "event":
        payload.setdefault("requires_ack", False)
        payload.setdefault("delivery_mode", "fire_and_forget")
        payload.setdefault("event_seq", 0)
        if "data" in payload and "body" not in payload:
            payload["body"] = payload.pop("data")
    raw["payload"] = payload
    return raw


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _raise_node_error(status: int, code: str, message: str, node_id: str | None) -> None:
    raise HTTPException(
        status_code=status,
        detail={"error": {"code": code, "message": message, "details": {"node_id": node_id}}},
    )


@router.post("/node/hello")
async def compat_hello(
    request: Request,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    raw = await request.json()
    raw = _translate_envelope(raw)
    node_id = raw.get("node_id", "")
    if not node_id:
        _raise_node_error(400, "missing_node_id", "node_id is required", None)
    if not _NODE_ID_PATTERN.match(node_id):
        _raise_node_error(400, "invalid_node_id", "node_id must match ^[a-z0-9-]{3,64}$", node_id)
    allowed, retry = check_node_rate(node_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": str(retry)},
            detail="Rate limit exceeded",
        )
    await upsert_node(settings.gateway_db_path, raw)
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        await db.execute(
            "INSERT OR IGNORE INTO node_config (node_id) VALUES (?)", (node_id,)
        )
        await db.commit()
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM node_config WHERE node_id=?", (node_id,)
        ) as cur:
            cfg = await cur.fetchone()
    return {
        "protocol": "CNPv1",
        "message_type": "register_ack",
        "registered": True,
        "config": {
            "heartbeat_interval_sec": cfg["heartbeat_interval_sec"] if cfg else 30,
            "report_interval_sec": cfg["report_interval_sec"] if cfg else 60,
            "zone": raw.get("payload", {}).get("zone", "unassigned"),
            "permissions": ["control", "configuration", "maintenance"],
        },
    }


@router.post("/node/heartbeat")
async def compat_heartbeat(
    request: Request,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    raw = await request.json()
    raw = _translate_envelope(raw)
    await update_heartbeat(settings.gateway_db_path, raw)
    return {"status": "ok"}


@router.post("/node/event")
async def compat_event(
    request: Request,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    raw = await request.json()
    raw = _translate_envelope(raw)
    await insert_event(settings.gateway_db_path, raw)
    return {"status": "ok", "event_id": raw["message_id"]}


@router.post("/node/error")
async def compat_error(
    request: Request,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    raw = await request.json()
    raw = _translate_envelope(raw)
    await insert_error(settings.gateway_db_path, raw)
    return {"status": "ok"}


@router.post("/node/command_result")
async def compat_command_result(
    request: Request,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    raw = await request.json()
    raw = _translate_envelope(raw)
    await upsert_command_result(settings.gateway_db_path, raw)
    return {"status": "ok"}


@router.get("/node/commands/{node_id}")
async def compat_get_commands(
    node_id: str,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM commands
               WHERE node_id=? AND status='queued'
               ORDER BY issued_ts_utc ASC LIMIT 1""",
            (node_id,),
        ) as cur:
            cmd = await cur.fetchone()
        if not cmd:
            return {"command": None}
        cmd = dict(cmd)
        await db.execute(
            "UPDATE commands SET status='pending' WHERE command_id=?",
            (cmd["command_id"],),
        )
        await db.commit()
    arguments = json.loads(cmd.get("arguments_json") or "{}")
    return {
        "protocol": "CNPv1",
        "message_type": "command",
        "node_id": node_id,
        "timestamp": _now(),
        "payload": {
            "command_id": cmd["command_id"],
            "command_type": cmd["command_type"],
            "category": cmd["category"],
            "params": arguments,
            "timeout_ms": cmd.get("timeout_ms", 15000),
        },
        "command": True,
    }
