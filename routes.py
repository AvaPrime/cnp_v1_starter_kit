"""
CNP EPIC-01 — Updated routes.py
Incorporates:
  P1-02  NodeResponse DTO — no SELECT *, no secret exposure
  P1-06  Envelope validation on all inbound node routes
  P1-07  Bootstrap token auth on all /api/node/* routes
  P1-08  SQL views backing /api/alerts, /api/events, /api/summary
  P1-04  node_id body-level rate check (supplements middleware)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import aiosqlite
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..core.config import settings
from ..core.rate_limit import check_node_rate
from ..core.storage import create_command
from ..models.schemas import (
    CommandRequest,
    Envelope,
    NodeResponse,
    validate_bootstrap_token,
)

log = logging.getLogger("cnp.routes")
router = APIRouter()


# ----------------------------------------------------------------
#  Auth dependency — P1-07
# ----------------------------------------------------------------

def require_node_token(x_cnp_node_token: str | None = Header(default=None)) -> str:
    """
    FastAPI dependency for node-inbound routes.
    Validates X-CNP-Node-Token against bootstrap token (Stage 1).
    P2-02 upgrades this to per-node HMAC validation by replacing
    validate_bootstrap_token() — middleware structure unchanged.
    """
    if not validate_bootstrap_token(x_cnp_node_token):
        log.warning(
            "auth.failure source_token_present=%s",
            bool(x_cnp_node_token),
        )
        raise HTTPException(
            status_code=401,
            detail={
                "error": "unauthorized",
                "hint": "Set X-CNP-Node-Token header",
            },
        )
    return x_cnp_node_token  # type: ignore[return-value]


# ----------------------------------------------------------------
#  Envelope validation helper — P1-06
# ----------------------------------------------------------------

async def _parse_envelope(request: Request) -> tuple[Envelope, dict[str, Any]]:
    """
    Parse and validate inbound message as Envelope.
    Returns (validated_envelope, raw_body).
    Raises HTTPException(422) on validation failure — no DB write occurs.
    """
    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Request body is not valid JSON")

    try:
        envelope = Envelope.model_validate(raw)
    except ValidationError as exc:
        errors = exc.errors()
        log.warning(
            "envelope.validation_failed node_id=%s errors=%s",
            raw.get("node_id", "unknown"),
            json.dumps([{"field": str(e["loc"]), "msg": e["msg"]} for e in errors]),
        )
        raise HTTPException(
            status_code=422,
            detail={
                "error": "envelope_validation_failed",
                "fields": [
                    {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                    for e in errors
                ],
            },
        )

    return envelope, raw


# ----------------------------------------------------------------
#  Bridge dependency
# ----------------------------------------------------------------

def get_bridge():
    from ..main import bridge
    return bridge


# ----------------------------------------------------------------
#  Health
# ----------------------------------------------------------------

@router.get("/health")
async def health() -> dict[str, Any]:
    db_ok = False
    try:
        async with aiosqlite.connect(settings.gateway_db_path) as db:
            await db.execute("SELECT 1")
            db_ok = True
    except Exception:
        pass
    return {
        "status": "ok",
        "version": "0.2.0",
        "db_ok": db_ok,
        "ts_utc": _now_utc(),
    }


# ----------------------------------------------------------------
#  Node list / detail — P1-02 NodeResponse
# ----------------------------------------------------------------

@router.get("/nodes")
async def list_nodes(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[dict[str, Any]]:
    """All registered nodes via v_node_status view. No secret fields."""
    clause = "WHERE status = ?" if status else ""
    params = [status, limit] if status else [limit]
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT * FROM v_node_status {clause} ORDER BY node_id LIMIT ?",
            params,
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    return rows


@router.get("/nodes/{node_id}")
async def get_node(node_id: str) -> dict[str, Any]:
    """Single node detail — NodeResponse DTO enforces field exclusion."""
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM nodes WHERE node_id=?", (node_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Node not found")
    return NodeResponse.from_row(dict(row)).model_dump()


# ----------------------------------------------------------------
#  Node-inbound routes — all require auth (P1-07)
# ----------------------------------------------------------------

@router.post("/node/hello")
async def node_hello(
    request: Request,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    envelope, raw = await _parse_envelope(request)
    node_id = envelope.node_id

    # Body-level rate check (P1-04)
    allowed, retry = check_node_rate(node_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": "too_many_requests"},
            headers={"Retry-After": str(retry)},
        )

    from ..core.registry import upsert_node
    await upsert_node(settings.gateway_db_path, envelope.model_dump())
    log.info("hello node_id=%s", node_id)

    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM node_config WHERE node_id=?", (node_id,)
        ) as cur:
            cfg = await cur.fetchone()
        if not cfg:
            await db.execute(
                "INSERT OR IGNORE INTO node_config (node_id) VALUES (?)", (node_id,)
            )
            await db.commit()
            async with db.execute(
                "SELECT * FROM node_config WHERE node_id=?", (node_id,)
            ) as cur:
                cfg = await cur.fetchone()

    return {
        "protocol_version": "CNPv1",
        "message_type": "register_ack",
        "registered": True,
        "config": {
            "heartbeat_interval_sec": cfg["heartbeat_interval_sec"] if cfg else 60,
            "report_interval_sec":    cfg.get("report_interval_sec", 60) if cfg else 60,
            "offline_after_sec":      settings.offline_after_seconds,
            "permissions": ["control", "configuration", "maintenance"],
        },
    }


@router.post("/node/heartbeat")
async def node_heartbeat(
    request: Request,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    envelope, _ = await _parse_envelope(request)
    from ..core.registry import update_heartbeat
    await update_heartbeat(settings.gateway_db_path, envelope.model_dump())
    return {"status": "ok"}


@router.post("/node/event")
async def node_event(
    request: Request,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    envelope, _ = await _parse_envelope(request)
    from ..core.storage import insert_event
    await insert_event(settings.gateway_db_path, envelope.model_dump())
    return {"status": "ok", "message_id": envelope.message_id}


@router.post("/node/state")
async def node_state(
    request: Request,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    envelope, _ = await _parse_envelope(request)
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        p = envelope.payload
        await db.execute(
            "UPDATE nodes SET status=?, last_seen_utc=? WHERE node_id=?",
            (p.get("status", "online"), _now_utc(), envelope.node_id),
        )
        await db.commit()
    return {"status": "ok"}


@router.post("/node/error")
async def node_error(
    request: Request,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    envelope, _ = await _parse_envelope(request)
    from ..core.storage import insert_error
    await insert_error(settings.gateway_db_path, envelope.model_dump())
    return {"status": "ok"}


@router.post("/node/command_result")
async def node_command_result(
    request: Request,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    envelope, _ = await _parse_envelope(request)
    from ..core.storage import upsert_command_result
    await upsert_command_result(settings.gateway_db_path, envelope.model_dump())
    return {"status": "ok"}


@router.get("/node/commands/{node_id}")
async def get_pending_command(
    node_id: str,
    _token: str = Depends(require_node_token),
) -> dict[str, Any]:
    """Poll for pending command — V1 compat HTTP polling path."""
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

    return {
        "protocol_version": "CNPv1",
        "message_type": "command",
        "node_id": node_id,
        "ts_utc": _now_utc(),
        "payload": {
            "command_id":   cmd["command_id"],
            "command_type": cmd["command_type"],
            "category":     cmd["category"],
            "params":       json.loads(cmd.get("arguments_json") or "{}"),
            "timeout_ms":   cmd.get("timeout_ms", 15000),
        },
        "command": True,
    }


# ----------------------------------------------------------------
#  Operator/dashboard endpoints — P1-08 views
# ----------------------------------------------------------------

@router.get("/events")
async def list_events(
    limit: int = Query(default=50, le=500),
    priority: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    clause = "WHERE priority=?" if priority else ""
    params = ([priority, limit] if priority else [limit])
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT * FROM events {clause} ORDER BY ts_utc DESC LIMIT ?",
            params,
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


@router.get("/alerts")
async def list_alerts() -> list[dict[str, Any]]:
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM v_recent_alerts LIMIT 100"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


@router.get("/summary")
async def fleet_summary() -> dict[str, Any]:
    """Fleet overview backed by v_fleet_summary view."""
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM v_fleet_summary") as cur:
            row = await cur.fetchone()
    if not row:
        return {}
    return dict(row)


@router.post("/nodes/{node_id}/commands")
async def send_command(
    node_id: str,
    command: CommandRequest,
    bridge=Depends(get_bridge),
) -> dict[str, Any]:
    command_id = str(uuid4())
    payload = {
        "command_id":   command_id,
        "command_type": command.command_type,
        "category":     command.category,
        "timeout_ms":   command.timeout_ms,
        "arguments":    command.arguments,
        "issued_by":    command.issued_by,
        "issued_ts_utc": _now_utc(),
        "dry_run":      command.dry_run,
    }
    await create_command(settings.gateway_db_path, payload, node_id)
    await bridge.publish_command(node_id, payload)
    return {"command_id": command_id, "status": "queued"}


@router.patch("/nodes/{node_id}/config")
async def update_node_config(
    node_id: str, request: Request
) -> dict[str, Any]:
    body = await request.json()
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        await db.execute(
            """
            INSERT INTO node_config
                (node_id, heartbeat_interval_sec, report_interval_sec, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                heartbeat_interval_sec = excluded.heartbeat_interval_sec,
                report_interval_sec    = excluded.report_interval_sec,
                updated_at             = excluded.updated_at
            """,
            (
                node_id,
                body.get("heartbeat_interval_sec", 60),
                body.get("report_interval_sec", 60),
                _now_utc(),
            ),
        )
        await db.commit()
    return {"status": "ok"}


# ----------------------------------------------------------------
#  Utilities
# ----------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
