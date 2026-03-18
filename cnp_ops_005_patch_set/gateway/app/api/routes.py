from __future__ import annotations

import aiosqlite
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from ..core.storage import create_command
from ..models.schemas import CommandRequest
from ..ops.api_models import NodeResponse

router = APIRouter()


def get_bridge(request: Request):
    return request.app.state.bridge


def get_db_path(request: Request) -> str:
    return request.app.state.db_path


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/nodes", response_model=list[NodeResponse])
async def list_nodes(request: Request):
    db_path = get_db_path(request)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT node_id, node_name, node_type, status, firmware_version,
                   COALESCE(json_extract(metadata_json, '$.zone'), 'unknown') AS zone,
                   capabilities_json, last_seen_utc, battery_pct, last_rssi AS wifi_rssi,
                   queue_depth
            FROM nodes ORDER BY node_id
            """
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    return rows


@router.get("/nodes/{node_id}", response_model=NodeResponse)
async def get_node(node_id: str, request: Request):
    db_path = get_db_path(request)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT node_id, node_name, node_type, status, firmware_version,
                   COALESCE(json_extract(metadata_json, '$.zone'), 'unknown') AS zone,
                   capabilities_json, last_seen_utc, battery_pct, last_rssi AS wifi_rssi,
                   queue_depth
            FROM nodes WHERE node_id=?
            """,
            (node_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Node not found")
    return dict(row)


@router.post("/nodes/{node_id}/commands")
async def send_command(
    node_id: str,
    command: CommandRequest,
    request: Request,
    bridge=Depends(get_bridge),
):
    command_id = str(uuid4())
    payload = {
        "command_id": command_id,
        "command_type": command.command_type,
        "category": command.category,
        "timeout_ms": command.timeout_ms,
        "arguments": command.arguments,
        "issued_by": command.issued_by,
        "issued_ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dry_run": command.dry_run,
    }
    db_path = get_db_path(request)
    await create_command(db_path, payload, node_id)
    if request.app.state.enable_bridge:
        await bridge.publish_command(node_id, payload)
    return {"command_id": command_id, "status": "queued"}
