"""
CNP-OPS-004 — REST API surface.

All endpoints are read-heavy at Phase O2.
Write endpoints: acknowledge, resolve, cancel.
Operator-facing — no node token required (bearer auth
from dashboard/Codessa Core only).

Mounted at /api/ops in main.py.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..core.config import settings
from .db import (
    get_anomalies,
    get_anomaly,
    get_latest_score,
    update_anomaly_status,
    update_reflex_status,
)
from .models import AnomalyStatus, ReflexExecutionStatus
from .scoring import compute_fleet_score, compute_node_score

log = logging.getLogger("cnp.ops.api")
router = APIRouter()


# ----------------------------------------------------------------
#  Request / Response helpers
# ----------------------------------------------------------------

class AcknowledgeRequest(BaseModel):
    acknowledged_by: str = "operator"


class ResolveRequest(BaseModel):
    resolution_note: str | None = None


# ----------------------------------------------------------------
#  Anomaly endpoints
# ----------------------------------------------------------------

@router.get("/anomalies")
async def list_anomalies(
    status: str | None = Query(default=None),
    node_id: str | None = Query(default=None),
    limit: int = Query(default=50, le=500),
) -> list[dict[str, Any]]:
    """
    List anomalies, optionally filtered by status and/or node.
    Default returns all non-resolved anomalies.
    """
    effective_status = status  # None returns all
    return await get_anomalies(
        settings.gateway_db_path,
        status=effective_status,
        node_id=node_id,
        limit=limit,
    )


@router.get("/anomalies/{anomaly_id}")
async def get_anomaly_detail(anomaly_id: str) -> dict[str, Any]:
    row = await get_anomaly(settings.gateway_db_path, anomaly_id)
    if not row:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return row


@router.post("/anomalies/{anomaly_id}/acknowledge")
async def acknowledge_anomaly(
    anomaly_id: str, body: AcknowledgeRequest
) -> dict[str, Any]:
    row = await get_anomaly(settings.gateway_db_path, anomaly_id)
    if not row:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    if row["status"] in (AnomalyStatus.RESOLVED.value, AnomalyStatus.ACKNOWLEDGED.value):
        raise HTTPException(
            status_code=409,
            detail=f"Anomaly is already {row['status']}",
        )
    await update_anomaly_status(
        settings.gateway_db_path,
        anomaly_id,
        AnomalyStatus.ACKNOWLEDGED,
        acknowledged_by=body.acknowledged_by,
    )
    return {"anomaly_id": anomaly_id, "status": "acknowledged"}


@router.post("/anomalies/{anomaly_id}/resolve")
async def resolve_anomaly(
    anomaly_id: str, body: ResolveRequest
) -> dict[str, Any]:
    row = await get_anomaly(settings.gateway_db_path, anomaly_id)
    if not row:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    if row["status"] == AnomalyStatus.RESOLVED.value:
        raise HTTPException(status_code=409, detail="Anomaly already resolved")
    await update_anomaly_status(
        settings.gateway_db_path,
        anomaly_id,
        AnomalyStatus.RESOLVED,
    )
    return {"anomaly_id": anomaly_id, "status": "resolved"}


# ----------------------------------------------------------------
#  Health score endpoints
# ----------------------------------------------------------------

@router.get("/fleet/score")
async def fleet_score() -> dict[str, Any]:
    """Compute and return the current fleet-wide health score."""
    record = await compute_fleet_score(settings.gateway_db_path)
    return record.model_dump()


@router.get("/nodes/{node_id}/score")
async def node_score(node_id: str) -> dict[str, Any]:
    """Compute and return the current health score for a node."""
    import aiosqlite
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM nodes WHERE node_id=?", (node_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Node not found")
    record = await compute_node_score(
        settings.gateway_db_path, node_id, dict(row)
    )
    return record.model_dump()


@router.get("/fleet/health")
async def fleet_health() -> dict[str, Any]:
    """
    Per-node health summary for the dashboard.
    Returns latest cached score per node (does not recompute).
    """
    from .db import get_all_node_scores
    scores = await get_all_node_scores(settings.gateway_db_path)
    active_anomalies = await get_anomalies(
        settings.gateway_db_path, status="active", limit=500
    )
    anomaly_counts: dict[str, int] = {}
    for a in active_anomalies:
        nid = a.get("node_id") or ""
        anomaly_counts[nid] = anomaly_counts.get(nid, 0) + 1

    return {
        "nodes": [
            {
                **s,
                "active_anomaly_count": anomaly_counts.get(s.get("scope_id", ""), 0),
            }
            for s in scores
        ],
        "total_nodes": len(scores),
        "unhealthy_count": sum(1 for s in scores if s.get("health_score", 100) < 60),
    }


# ----------------------------------------------------------------
#  Reflex simulation
# ----------------------------------------------------------------

@router.post("/reflex/rules/{rule_id}/simulate")
async def simulate_rule(
    rule_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """
    Dry-run a rule against provided evidence payload.
    Does not persist any anomaly or action.
    Returns what would have been raised.
    """
    from .rules import get_rule as _get_rule
    rule = _get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    node_id = body.get("node_id", "sim-node-01")
    evidence = body.get("evidence", {})

    return {
        "simulation": True,
        "rule_id": rule_id,
        "rule_name": rule.name,
        "would_raise": {
            "anomaly_type":   rule.anomaly_type,
            "category":       rule.category,
            "severity":       rule.severity,
            "confidence":     rule.confidence,
            "node_id":        node_id,
        },
        "would_execute_reflex": (
            {
                "action_type":  rule.default_reflex.action_type,
                "safety_level": rule.default_reflex.safety_level,
                "payload":      rule.default_reflex.payload,
            }
            if rule.default_reflex
            else None
        ),
        "evidence_received": evidence,
    }


# ----------------------------------------------------------------
#  Reflex action cancel
# ----------------------------------------------------------------

@router.post("/reflex/actions/{action_id}/cancel")
async def cancel_reflex_action(action_id: str) -> dict[str, Any]:
    """
    Cancel a pending reflex action before it executes.
    Only valid for status=pending.
    """
    import aiosqlite
    async with aiosqlite.connect(settings.gateway_db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM ops_reflex_actions WHERE action_id=?", (action_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Reflex action not found")
    if dict(row)["execution_status"] != ReflexExecutionStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel — action is {dict(row)['execution_status']}",
        )
    await update_reflex_status(
        settings.gateway_db_path,
        action_id,
        ReflexExecutionStatus.CANCELLED,
        {"cancelled_by": "operator"},
    )
    return {"action_id": action_id, "status": "cancelled"}
