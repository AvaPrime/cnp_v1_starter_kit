from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    rule_id: str
    anomaly_type: str
    name: str
    category: str
    severity: str
    default_action: str
    suppression_sec: int
    threshold: dict[str, Any] = field(default_factory=dict)


RULES: dict[str, RuleDefinition] = {
    "A-001": RuleDefinition(
        rule_id="A-001",
        anomaly_type="queue_congestion",
        name="Queue Congestion",
        category="performance",
        severity="warning",
        default_action="publish_config_update",
        suppression_sec=300,
        threshold={"queue_depth": 10, "consecutive_hits": 3},
    ),
    "A-002": RuleDefinition(
        rule_id="A-002",
        anomaly_type="memory_leak_suspected",
        name="Memory Leak Suspected",
        category="reliability",
        severity="warning",
        default_action="request_module_status",
        suppression_sec=300,
        threshold={"consecutive_hits": 3},
    ),
    "A-003": RuleDefinition(
        rule_id="A-003",
        anomaly_type="weak_connectivity",
        name="Weak Connectivity",
        category="connectivity",
        severity="warning",
        default_action="publish_config_update",
        suppression_sec=300,
        threshold={"wifi_rssi": -80, "window_sec": 300, "min_samples": 3},
    ),
    "A-004": RuleDefinition(
        rule_id="A-004",
        anomaly_type="command_lag",
        name="Command Lag",
        category="performance",
        severity="warning",
        default_action="pause_non_critical_commands",
        suppression_sec=180,
        threshold={"p95_ms": 5000, "min_samples": 3},
    ),
    "A-005": RuleDefinition(
        rule_id="A-005",
        anomaly_type="offline_flapping",
        name="Offline Flapping",
        category="stability",
        severity="warning",
        default_action="set_node_degraded",
        suppression_sec=300,
        threshold={"transitions": 4, "window_sec": 600},
    ),
}
