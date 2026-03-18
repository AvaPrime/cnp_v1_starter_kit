from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class AnomalyRecord:
    anomaly_id: str
    detected_ts_utc: str
    anomaly_type: str
    category: str
    severity: str
    score: float
    confidence: float
    status: str
    evidence: dict[str, Any]
    source_rule_id: str
    node_id: str | None = None
    zone: str | None = None
    recommended_action: str | None = None
    correlation_id: str | None = None
    resolved_ts_utc: str | None = None


@dataclass(slots=True)
class ReflexAction:
    action_id: str
    anomaly_id: str
    issued_ts_utc: str
    action_type: str
    action_payload: dict[str, Any]
    execution_status: str
    node_id: str | None = None
    result: dict[str, Any] | None = None
    safe_mode: bool = True
    requires_human: bool = False
    completed_ts_utc: str | None = None


@dataclass(slots=True)
class ScoreCard:
    scope_type: str
    scope_id: str
    ts_utc: str
    health_score: float
    reliability_score: float
    security_score: float
    performance_score: float
    maintainability_score: float
    responsiveness_score: float
    evidence: dict[str, Any] = field(default_factory=dict)
