"""
CNP-OPS-004 — Pydantic models, enums, and typed snapshots.

All persistence-facing models use str IDs (ULID recommended).
All timestamps are ISO-8601 UTC strings ending in Z.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ----------------------------------------------------------------
#  Enumerations
# ----------------------------------------------------------------

class AnomalyStatus(str, Enum):
    DETECTED     = "detected"
    ACTIVE       = "active"
    ACKNOWLEDGED = "acknowledged"
    SUPPRESSED   = "suppressed"
    ESCALATED    = "escalated"
    RESOLVED     = "resolved"


class AnomalyCategory(str, Enum):
    RELIABILITY   = "reliability"
    PERFORMANCE   = "performance"
    SECURITY      = "security"
    CONNECTIVITY  = "connectivity"
    FLEET         = "fleet"


class AnomalySeverity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    ERROR    = "error"
    CRITICAL = "critical"


class ReflexActionType(str, Enum):
    OBSERVE_ONLY           = "observe_only"
    EMIT_ALERT             = "emit_alert"
    PUBLISH_CONFIG_UPDATE  = "publish_config_update"
    SET_NODE_DEGRADED      = "set_node_degraded"
    QUARANTINE_NODE        = "quarantine_node"
    THROTTLE_NODE          = "throttle_node"
    REQUEST_REBOOT         = "request_reboot"
    RETIRE_STALE_COMMANDS  = "retire_stale_commands"
    PAUSE_ZONE_AUTOMATION  = "pause_zone_automation"
    REQUIRE_HUMAN_APPROVAL = "require_human_approval"


class ReflexExecutionStatus(str, Enum):
    PENDING     = "pending"
    EXECUTING   = "executing"
    COMPLETED   = "completed"
    FAILED      = "failed"
    CANCELLED   = "cancelled"
    SUPERSEDED  = "superseded"


class SafetyLevel(int, Enum):
    """
    L0 — log only
    L1 — notify only
    L2 — reversible config change  (auto-execute allowed)
    L3 — disruptive but recoverable (requires allowlist)
    L4 — human approval required
    """
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3
    L4 = 4


class ScopeType(str, Enum):
    NODE  = "node"
    ZONE  = "zone"
    FLEET = "fleet"


# ----------------------------------------------------------------
#  In-memory heartbeat snapshot (not persisted directly)
# ----------------------------------------------------------------

@dataclass
class HeartbeatSnapshot:
    node_id:         str
    ts_utc:          str
    free_heap_bytes: int | None
    wifi_rssi:       int | None
    queue_depth:     int
    battery_pct:     float | None
    status:          str
    seq:             int | None = None

    @property
    def ts(self) -> datetime:
        return datetime.fromisoformat(self.ts_utc.replace("Z", "+00:00"))


# ----------------------------------------------------------------
#  Pydantic models — API-facing
# ----------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return str(uuid4())


class AnomalyRecord(BaseModel):
    anomaly_id:          str     = Field(default_factory=_new_id)
    detected_ts_utc:     str     = Field(default_factory=_now_utc)
    node_id:             str | None = None
    zone:                str | None = None
    anomaly_type:        str
    category:            AnomalyCategory
    severity:            AnomalySeverity
    score:               float   = Field(ge=0.0, le=1.0)
    confidence:          float   = Field(ge=0.0, le=1.0)
    status:              AnomalyStatus = AnomalyStatus.DETECTED
    evidence_json:       dict[str, Any] = Field(default_factory=dict)
    recommended_action:  str | None = None
    source_rule_id:      str
    correlation_id:      str | None = None
    acknowledged_by:     str | None = None
    acknowledged_ts_utc: str | None = None
    resolved_ts_utc:     str | None = None


class ReflexActionRecord(BaseModel):
    action_id:            str     = Field(default_factory=_new_id)
    anomaly_id:           str
    issued_ts_utc:        str     = Field(default_factory=_now_utc)
    node_id:              str | None = None
    action_type:          ReflexActionType
    action_payload_json:  dict[str, Any] = Field(default_factory=dict)
    safety_level:         SafetyLevel = SafetyLevel.L2
    execution_status:     ReflexExecutionStatus = ReflexExecutionStatus.PENDING
    result_json:          dict[str, Any] | None = None
    safe_mode:            bool = True
    requires_human:       bool = False
    completed_ts_utc:     str | None = None


class HealthScoreRecord(BaseModel):
    score_id:               str   = Field(default_factory=_new_id)
    ts_utc:                 str   = Field(default_factory=_now_utc)
    scope_type:             ScopeType
    scope_id:               str
    health_score:           float = Field(ge=0, le=100)
    reliability_score:      float = Field(ge=0, le=100)
    security_score:         float = Field(ge=0, le=100)
    performance_score:      float = Field(ge=0, le=100)
    maintainability_score:  float = Field(ge=0, le=100)
    responsiveness_score:   float = Field(ge=0, le=100)
    evidence_json:          dict[str, Any] = Field(default_factory=dict)


class RuleStateRecord(BaseModel):
    rule_id:                   str
    scope_type:                ScopeType
    scope_id:                  str
    last_triggered_ts_utc:     str | None = None
    suppression_until_ts_utc:  str | None = None
    consecutive_hits:          int = 0
    consecutive_recoveries:    int = 0
    last_anomaly_id:           str | None = None


class HeartbeatDailySummaryRecord(BaseModel):
    node_id:             str
    day_utc:             str
    min_free_heap_bytes: int | None = None
    max_free_heap_bytes: int | None = None
    avg_free_heap_bytes: float | None = None
    min_wifi_rssi:       int | None = None
    max_wifi_rssi:       int | None = None
    avg_wifi_rssi:       float | None = None
    min_queue_depth:     int | None = None
    max_queue_depth:     int | None = None
    avg_queue_depth:     float | None = None
    offline_transitions: int = 0
    heartbeat_count:     int = 0
    sample_count:        int = 0


# ----------------------------------------------------------------
#  Rule definition (loaded from YAML catalog)
# ----------------------------------------------------------------

@dataclass
class ReflexSpec:
    action_type:        str
    payload:            dict[str, Any] = field(default_factory=dict)
    safety_level:       int = 2
    requires_human:     bool = False


@dataclass
class RuleDefinition:
    rule_id:             str
    name:                str
    scope:               str         # "node" | "zone" | "fleet"
    anomaly_type:        str
    category:            str
    severity:            str
    consecutive_hits:    int = 1
    suppress_for_sec:    int = 300
    confidence:          float = 0.8
    default_reflex:      ReflexSpec | None = None
    requires_human_above_level: int = 3
    enabled:             bool = True
