from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from ..core.config import settings
from ..core.storage import create_command
from ..models.schemas import CommandRequest

router = APIRouter()


def get_bridge():
    from ..main import bridge
    return bridge


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/nodes")
async def list_nodes():
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM nodes ORDER BY node_id") as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    return rows


@router.get("/nodes/{node_id}")
async def get_node(node_id: str):
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Node not found")
    return dict(row)


@router.post("/nodes/{node_id}/commands")
async def send_command(node_id: str, command: CommandRequest, bridge=Depends(get_bridge)):
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
    await create_command(settings.gateway_db_path, payload, node_id)
    await bridge.publish_command(node_id, payload)
    return {"command_id": command_id, "status": "queued"}
