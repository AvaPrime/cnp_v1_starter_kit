from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, HTTPException, Request

from .anomalies import OpsService
from .api_models import (
    AnomalyLifecycleRequest,
    AnomalyResponse,
    ReflexActionResponse,
    RuleSimulationRequest,
    ScoreBreakdown,
    ScoreResponse,
)

router = APIRouter()
service = OpsService()


def _row_to_anomaly(row) -> AnomalyResponse:
    payload = dict(row)
    payload["evidence_json"] = json.loads(payload["evidence_json"])
    return AnomalyResponse(**payload)


def _row_to_action(row) -> ReflexActionResponse:
    payload = dict(row)
    payload["action_payload_json"] = json.loads(payload["action_payload_json"])
    payload["result_json"] = json.loads(payload["result_json"]) if payload.get("result_json") else None
    payload["safe_mode"] = bool(payload["safe_mode"])
    payload["requires_human"] = bool(payload["requires_human"])
    return ReflexActionResponse(**payload)


@router.get("/anomalies", response_model=list[AnomalyResponse])
async def list_anomalies(request: Request):
    rows = await service.list_anomalies(request.app.state.db_path)
    return [
        AnomalyResponse(
            **{
                **row,
                "evidence_json": json.loads(row["evidence_json"]),
            }
        )
        for row in rows
    ]


@router.get("/anomalies/{anomaly_id}", response_model=AnomalyResponse)
async def get_anomaly(anomaly_id: str, request: Request):
    async with aiosqlite.connect(request.app.state.db_path) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute("SELECT * FROM ops_anomalies WHERE anomaly_id=?", (anomaly_id,))).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return _row_to_anomaly(row)


@router.post("/anomalies/{anomaly_id}/acknowledge", response_model=AnomalyResponse)
async def acknowledge_anomaly(anomaly_id: str, body: AnomalyLifecycleRequest, request: Request):
    async with aiosqlite.connect(request.app.state.db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("UPDATE ops_anomalies SET status='acknowledged' WHERE anomaly_id=?", (anomaly_id,))
        await db.commit()
        row = await (await db.execute("SELECT * FROM ops_anomalies WHERE anomaly_id=?", (anomaly_id,))).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return _row_to_anomaly(row)


@router.post("/anomalies/{anomaly_id}/resolve", response_model=AnomalyResponse)
async def resolve_anomaly(anomaly_id: str, body: AnomalyLifecycleRequest, request: Request):
    async with aiosqlite.connect(request.app.state.db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "UPDATE ops_anomalies SET status='resolved', resolved_ts_utc=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE anomaly_id=?",
            (anomaly_id,),
        )
        await db.commit()
        row = await (await db.execute("SELECT * FROM ops_anomalies WHERE anomaly_id=?", (anomaly_id,))).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return _row_to_anomaly(row)


@router.get("/fleet/score", response_model=ScoreResponse)
async def fleet_score(request: Request):
    score = await service.scoring.calculate_fleet_score(request.app.state.db_path)
    await service.scoring.persist_score(request.app.state.db_path, score)
    return ScoreResponse(
        scope_type=score.scope_type,
        scope_id=score.scope_id,
        ts_utc=score.ts_utc,
        breakdown=ScoreBreakdown(
            health_score=score.health_score,
            reliability_score=score.reliability_score,
            security_score=score.security_score,
            performance_score=score.performance_score,
            maintainability_score=score.maintainability_score,
            responsiveness_score=score.responsiveness_score,
            evidence_json=score.evidence,
        ),
    )


@router.get("/nodes/{node_id}/score", response_model=ScoreResponse)
async def node_score(node_id: str, request: Request):
    score = await service.scoring.calculate_node_score(request.app.state.db_path, node_id)
    await service.scoring.persist_score(request.app.state.db_path, score)
    return ScoreResponse(
        scope_type=score.scope_type,
        scope_id=score.scope_id,
        ts_utc=score.ts_utc,
        breakdown=ScoreBreakdown(
            health_score=score.health_score,
            reliability_score=score.reliability_score,
            security_score=score.security_score,
            performance_score=score.performance_score,
            maintainability_score=score.maintainability_score,
            responsiveness_score=score.responsiveness_score,
            evidence_json=score.evidence,
        ),
    )


@router.get("/fleet/health")
async def fleet_health(request: Request):
    async with aiosqlite.connect(request.app.state.db_path) as db:
        db.row_factory = aiosqlite.Row
        rows = await (
            await db.execute(
                """
                SELECT node_id, day_utc, min_free_heap_bytes, max_free_heap_bytes, avg_free_heap_bytes,
                       min_wifi_rssi, max_wifi_rssi, avg_wifi_rssi,
                       min_queue_depth, max_queue_depth, avg_queue_depth, sample_count
                FROM heartbeat_daily_summary
                ORDER BY node_id, day_utc DESC
                """
            )
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/reflex/rules/{rule_id}/simulate")
async def simulate_rule(rule_id: str, body: RuleSimulationRequest, request: Request):
    anomalies = await service.detector.detect_node_anomalies(
        request.app.state.db_path,
        body.node_id,
        now_ts_utc=body.now_ts_utc.isoformat().replace("+00:00", "Z") if body.now_ts_utc else None,
    )
    for anomaly in anomalies:
        if anomaly.source_rule_id == rule_id:
            action = await service.healer.reflex_engine.plan(anomaly)
            return {"anomaly_id": anomaly.anomaly_id, "planned_action": action.action_type, "payload": action.action_payload}

    async with aiosqlite.connect(request.app.state.db_path) as db:
        db.row_factory = aiosqlite.Row
        row = await (
            await db.execute(
                "SELECT * FROM ops_anomalies WHERE node_id=? AND source_rule_id=? AND status IN ('open', 'acknowledged') ORDER BY detected_ts_utc DESC LIMIT 1",
                (body.node_id, rule_id),
            )
        ).fetchone()
    if row is not None:
        anomaly = _row_to_anomaly(row)
        from .models import AnomalyRecord

        existing = AnomalyRecord(
            anomaly_id=anomaly.anomaly_id,
            detected_ts_utc=anomaly.detected_ts_utc,
            node_id=anomaly.node_id,
            zone=anomaly.zone,
            anomaly_type=anomaly.anomaly_type,
            category=anomaly.category,
            severity=anomaly.severity,
            score=anomaly.score,
            confidence=anomaly.confidence,
            status=anomaly.status,
            evidence=anomaly.evidence_json,
            recommended_action=anomaly.recommended_action,
            source_rule_id=anomaly.source_rule_id,
            correlation_id=anomaly.correlation_id,
            resolved_ts_utc=anomaly.resolved_ts_utc,
        )
        planned = await service.healer.reflex_engine.plan(existing)
        return {"anomaly_id": anomaly.anomaly_id, "planned_action": planned.action_type, "payload": planned.action_payload}
    raise HTTPException(status_code=404, detail="Rule did not trigger")


@router.post("/reflex/actions/{action_id}/cancel", response_model=ReflexActionResponse)
async def cancel_action(action_id: str, request: Request):
    async with aiosqlite.connect(request.app.state.db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "UPDATE ops_reflex_actions SET execution_status='cancelled', completed_ts_utc=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE action_id=?",
            (action_id,),
        )
        await db.commit()
        row = await (
            await db.execute("SELECT * FROM ops_reflex_actions WHERE action_id=?", (action_id,))
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return _row_to_action(row)
