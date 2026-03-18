from __future__ import annotations
import logging
from typing import Any

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.auth import provision_node_secret, rotate_node_secret
from ..core.config import settings

log = logging.getLogger("cnp.admin")
router = APIRouter()


def _raise_node_error(status: int, code: str, message: str, node_id: str | None) -> None:
    raise HTTPException(
        status_code=status,
        detail={"error": {"code": code, "message": message, "details": {"node_id": node_id}}},
    )


@router.get("/fleet/status")
async def fleet_status() -> dict[str, Any]:
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT
                COALESCE(JSON_EXTRACT(metadata_json, '$.zone'), 'unassigned') AS zone,
                status,
                COUNT(*) AS count
            FROM nodes
            WHERE status != 'retired'
            GROUP BY zone, status
            ORDER BY zone, status
            """
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    zones: dict[str, dict[str, Any]] = {}
    for row in rows:
        z = row["zone"]
        if z not in zones:
            zones[z] = {"zone": z, "total": 0}
        zones[z][row["status"]] = row["count"]
        zones[z]["total"] += row["count"]
    return {
        "zones": list(zones.values()),
        "zone_count": len(zones),
    }


class ProvisionResponse(BaseModel):
    node_id: str
    secret: str
    instructions: str


@router.post("/nodes/{node_id}/provision")
async def provision_secret(node_id: str) -> ProvisionResponse:
    try:
        plain = await provision_node_secret(settings.gateway_db_path, node_id)
    except ValueError as exc:
        _raise_node_error(404, "node_not_found", "node_id not found", node_id)
    return ProvisionResponse(
        node_id=node_id,
        secret=plain,
        instructions=(
            "Store this secret on the node in NVS. "
            "Compute X-CNP-Node-Token as HMAC-SHA256(SHA256(secret), node_id). "
            "This secret is shown ONCE and cannot be retrieved."
        ),
    )


@router.post("/nodes/{node_id}/rotate-secret")
async def rotate_secret(node_id: str) -> ProvisionResponse:
    try:
        plain = await rotate_node_secret(settings.gateway_db_path, node_id)
    except ValueError as exc:
        _raise_node_error(404, "node_not_found", "node_id not found", node_id)
    return ProvisionResponse(
        node_id=node_id,
        secret=plain,
        instructions=(
            "The previous secret is now invalid. "
            "Deploy this new secret to the node via secure channel (USB/QR). "
            "This secret is shown ONCE."
        ),
    )
