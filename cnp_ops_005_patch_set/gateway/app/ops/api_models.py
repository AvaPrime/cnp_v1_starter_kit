from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class NodeResponse(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    zone: str = "unknown"
    status: str
    firmware_version: str
    capabilities_json: str
    last_seen_utc: str | None = None
    battery_pct: float | None = None
    wifi_rssi: int | None = None
    queue_depth: int = 0


class AnomalyResponse(BaseModel):
    anomaly_id: str
    detected_ts_utc: str
    node_id: str | None = None
    zone: str | None = None
    anomaly_type: str
    category: str
    severity: str
    score: float
    confidence: float
    status: str
    evidence_json: dict[str, Any]
    recommended_action: str | None = None
    source_rule_id: str
    correlation_id: str | None = None
    resolved_ts_utc: str | None = None


class ReflexActionResponse(BaseModel):
    action_id: str
    anomaly_id: str
    issued_ts_utc: str
    node_id: str | None = None
    action_type: str
    action_payload_json: dict[str, Any]
    execution_status: str
    result_json: dict[str, Any] | None = None
    safe_mode: bool = True
    requires_human: bool = False
    completed_ts_utc: str | None = None


class ScoreBreakdown(BaseModel):
    health_score: float = Field(ge=0, le=100)
    reliability_score: float = Field(ge=0, le=100)
    security_score: float = Field(ge=0, le=100)
    performance_score: float = Field(ge=0, le=100)
    maintainability_score: float = Field(ge=0, le=100)
    responsiveness_score: float = Field(ge=0, le=100)
    evidence_json: dict[str, Any]


class ScoreResponse(BaseModel):
    scope_type: Literal["node", "fleet", "zone"]
    scope_id: str
    ts_utc: str
    breakdown: ScoreBreakdown


class AnomalyLifecycleRequest(BaseModel):
    note: str | None = None


class RuleSimulationRequest(BaseModel):
    node_id: str
    now_ts_utc: datetime | None = None
