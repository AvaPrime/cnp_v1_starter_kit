"""
gateway/app/api/admin.py
────────────────────────
Admin endpoints — secret provisioning, rotation, fleet status.

AUDIT FIX (P0-05 / CRITICAL):
  All endpoints now require X-CNP-Admin-Token.
  Previously these were completely unauthenticated — any caller could
  retrieve or rotate node secrets.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from ..core.auth import provision_node_secret, rotate_node_secret
from ..core.config import settings
from ..core.db import db_connect

log = logging.getLogger("cnp.admin")
router = APIRouter()

# ---------------------------------------------------------------------------
# Admin token auth  (P0-05)
# ---------------------------------------------------------------------------

_ADMIN_TOKEN: str = os.environ.get("ADMIN_TOKEN", "")

if not _ADMIN_TOKEN:
    log.warning(
        "ADMIN_TOKEN env var not set — all admin endpoints will return 401. "
        "Set ADMIN_TOKEN in your environment or .env file."
    )


def require_admin_token(
    x_cnp_admin_token: str | None = Header(default=None),
) -> str:
    """
    Dependency: validates X-CNP-Admin-Token header against ADMIN_TOKEN env var.
    Deliberately separate from node bootstrap tokens — admin operations require
    a distinct, higher-privilege credential.
    """
    import hmac

    if not _ADMIN_TOKEN:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "code": "admin_not_configured",
                    "message": "ADMIN_TOKEN is not configured on this gateway",
                    "details": {},
                }
            },
        )
    if not x_cnp_admin_token:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "unauthorized",
                    "message": "X-CNP-Admin-Token header is required",
                    "details": {},
                    "hint": "Set X-CNP-Admin-Token header with the gateway admin token",
                }
            },
        )
    if not hmac.compare_digest(
        x_cnp_admin_token.strip(), _ADMIN_TOKEN.strip()
    ):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "unauthorized",
                    "message": "Invalid admin token",
                    "details": {},
                }
            },
        )
    return x_cnp_admin_token


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _raise_node_error(
    request: Request,
    status: int,
    code: str,
    message: str,
    node_id: str | None,
) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raise HTTPException(
        status_code=status,
        detail={
            "error": {
                "code": code,
                "message": message,
                "details": {"node_id": node_id},
                "timestamp": ts,
                "path": request.url.path,
            }
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/fleet/status", dependencies=[Depends(require_admin_token)])
async def fleet_status() -> dict[str, Any]:
    """Fleet status breakdown by zone and node status."""
    async with db_connect(settings.gateway_db_path) as db:
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


@router.post("/nodes/{node_id}/provision", dependencies=[Depends(require_admin_token)])
async def provision_secret(
    request: Request,
    node_id: str,
) -> ProvisionResponse:
    """
    Generate and store a new per-node HMAC secret.
    The plaintext secret is returned ONCE and cannot be retrieved again.
    """
    try:
        plain = await provision_node_secret(settings.gateway_db_path, node_id)
    except ValueError:
        _raise_node_error(request, 404, "node_not_found", "node_id not found", node_id)

    log.info("admin.provision node_id=%s", node_id)
    return ProvisionResponse(
        node_id=node_id,
        secret=plain,
        instructions=(
            "Store this secret on the node in NVS. "
            "Compute X-CNP-Node-Token as HMAC-SHA256(SHA256(secret), node_id). "
            "This secret is shown ONCE and cannot be retrieved."
        ),
    )


@router.post("/nodes/{node_id}/rotate-secret", dependencies=[Depends(require_admin_token)])
async def rotate_secret(
    request: Request,
    node_id: str,
) -> ProvisionResponse:
    """
    Rotate the per-node secret. The previous secret is immediately invalidated.
    """
    try:
        plain = await rotate_node_secret(settings.gateway_db_path, node_id)
    except ValueError:
        _raise_node_error(request, 404, "node_not_found", "node_id not found", node_id)

    log.info("admin.rotate node_id=%s", node_id)
    return ProvisionResponse(
        node_id=node_id,
        secret=plain,
        instructions=(
            "The previous secret is now invalid. "
            "Deploy this new secret to the node via secure channel (USB/QR). "
            "This secret is shown ONCE."
        ),
    )
