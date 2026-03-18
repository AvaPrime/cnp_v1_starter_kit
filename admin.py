"""
CNP EPIC-02 — P2-08 + provisioning API routes
Additional operator endpoints:

  GET  /api/summary            (already in routes.py — kept here for reference)
  GET  /api/fleet/status       per-zone node breakdown
  POST /api/nodes/{id}/rotate-secret   P2-02 secret rotation
  POST /api/nodes/{id}/ota     OTA trigger scaffold (Phase 4)

P2-07: compat endpoints inherit P1-07 auth — no weaker path.
       Enforced by mounting compat router with require_node_token dependency.
"""
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


# ----------------------------------------------------------------
#  Fleet status breakdown — P2-08
# ----------------------------------------------------------------

@router.get("/fleet/status")
async def fleet_status() -> dict[str, Any]:
    """
    Per-zone node breakdown using metadata_json.zone.
    Counts nodes per zone + their status distribution.
    """
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

    # Pivot into {zone: {status: count, total: N}}
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


# ----------------------------------------------------------------
#  Node provisioning — P2-02
# ----------------------------------------------------------------

class ProvisionResponse(BaseModel):
    node_id:      str
    secret:       str
    instructions: str


@router.post("/nodes/{node_id}/provision")
async def provision_secret(node_id: str) -> ProvisionResponse:
    """
    Generate and store a per-node HMAC secret.
    Returns the plain secret ONCE — not stored, cannot be retrieved again.
    The node must save this secret and use it to compute X-CNP-Node-Token.
    """
    try:
        plain = await provision_node_secret(settings.gateway_db_path, node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

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
    """
    Rotate the per-node HMAC secret. Invalidates the current secret immediately.
    The node will be unable to authenticate until it receives and stores the new secret.
    """
    try:
        plain = await rotate_node_secret(settings.gateway_db_path, node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return ProvisionResponse(
        node_id=node_id,
        secret=plain,
        instructions=(
            "The previous secret is now invalid. "
            "Deploy this new secret to the node via secure channel (USB/QR). "
            "This secret is shown ONCE."
        ),
    )
