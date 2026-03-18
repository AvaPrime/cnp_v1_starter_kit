# CNP-OPS-004 — Operational Intelligence Layer
**Codessa Node Protocol / Codessa Ecosystem**  
**Version:** 1.0  
**Status:** Proposed build spec  
**Purpose:** Turn CNP from a transport-and-control system into a self-observing, self-protecting, self-healing network.

## 1. Intent

CNP-OPS-004 adds a new layer above the gateway and fleet services:

- anomaly detection
- reflex engine
- fleet scoring
- auto-healing rules

This layer does not replace CNP-BOARD-003. It sits on top of it and consumes the signals that board already defines, including heartbeat metrics, queue depth, RSSI, auth failures, command lag, offline transitions, rate-limit breaches, dead-letter counts, configuration updates, and timeout reconciliation. It is designed to work with the engineering board’s fleet diagnostics surface, rate-limit events, timeout reconciliation, and node status views. fileciteturn2file0

## 2. Design goals

1. Detect failure early
2. Classify severity consistently
3. Respond automatically when safe
4. Escalate when automation is unsafe or exhausted
5. Score node and fleet health continuously
6. Leave a full audit trail of every diagnosis and reflex action
7. Remain transport-agnostic

## 3. Position in the architecture

```text
ESP32 / Node
   ↓
Gateway / Bridge / Registry
   ↓
CNP-OPS-004
   ├── Anomaly Detector
   ├── Reflex Engine
   ├── Fleet Scoring
   ├── Auto-Healing Executor
   └── Ops Event Log
   ↓
Codessa Core / Memory Cortex / Dashboard / Alerts
```

It consumes `heartbeats`, `events`, `errors`, `commands`, `acks`, fleet watcher transitions, rate-limit breach logs, authentication failures, and config / OTA state. It produces anomaly records, health scores, reflex actions, operator alerts, remediation recommendations, and summarized fleet intelligence.

## 4. Core modules

### 4.1 Anomaly Detection Engine
Finds patterns that indicate instability, degradation, security risk, congestion, drift, or impending failure.

### 4.2 Reflex Engine
Maps anomaly classes to actions: observe, warn, quarantine, reconfigure, restart, backoff, suppress, escalate to human.

### 4.3 Fleet Scoring Engine
Computes per-node, per-zone, and fleet-wide health scores.

### 4.4 Auto-Healing Executor
Runs approved corrective actions such as `config_update`, telemetry backoff, reboot request, node isolation, stale-command retirement, and degraded-mode changes.

### 4.5 Ops Event Log
Stores anomaly detections, rule evaluations, executed reflexes, failed reflexes, escalations, suppression windows, and recovery confirmations.

## 5. Data model additions

### 5.1 `ops_anomalies`
```sql
CREATE TABLE IF NOT EXISTS ops_anomalies (
  anomaly_id TEXT PRIMARY KEY,
  detected_ts_utc TEXT NOT NULL,
  node_id TEXT,
  zone TEXT,
  anomaly_type TEXT NOT NULL,
  category TEXT NOT NULL,
  severity TEXT NOT NULL,
  score REAL NOT NULL,
  confidence REAL NOT NULL,
  status TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  recommended_action TEXT,
  source_rule_id TEXT NOT NULL,
  correlation_id TEXT,
  resolved_ts_utc TEXT
);
```

### 5.2 `ops_reflex_actions`
```sql
CREATE TABLE IF NOT EXISTS ops_reflex_actions (
  action_id TEXT PRIMARY KEY,
  anomaly_id TEXT NOT NULL,
  issued_ts_utc TEXT NOT NULL,
  node_id TEXT,
  action_type TEXT NOT NULL,
  action_payload_json TEXT NOT NULL,
  execution_status TEXT NOT NULL,
  result_json TEXT,
  safe_mode INTEGER NOT NULL DEFAULT 1,
  requires_human INTEGER NOT NULL DEFAULT 0,
  completed_ts_utc TEXT
);
```

### 5.3 `ops_health_scores`
```sql
CREATE TABLE IF NOT EXISTS ops_health_scores (
  score_id TEXT PRIMARY KEY,
  ts_utc TEXT NOT NULL,
  scope_type TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  health_score REAL NOT NULL,
  reliability_score REAL NOT NULL,
  security_score REAL NOT NULL,
  performance_score REAL NOT NULL,
  maintainability_score REAL NOT NULL,
  evidence_json TEXT NOT NULL
);
```

### 5.4 `ops_rule_state`
```sql
CREATE TABLE IF NOT EXISTS ops_rule_state (
  rule_id TEXT NOT NULL,
  scope_type TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  last_triggered_ts_utc TEXT,
  suppression_until_ts_utc TEXT,
  consecutive_hits INTEGER NOT NULL DEFAULT 0,
  consecutive_recoveries INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (rule_id, scope_type, scope_id)
);
```

### 5.5 `heartbeat_daily_summary`
```sql
CREATE TABLE IF NOT EXISTS heartbeat_daily_summary (
  node_id TEXT NOT NULL,
  day_utc TEXT NOT NULL,
  min_free_heap_bytes INTEGER,
  max_free_heap_bytes INTEGER,
  avg_free_heap_bytes REAL,
  min_wifi_rssi INTEGER,
  max_wifi_rssi INTEGER,
  avg_wifi_rssi REAL,
  min_queue_depth INTEGER,
  max_queue_depth INTEGER,
  avg_queue_depth REAL,
  sample_count INTEGER NOT NULL,
  PRIMARY KEY (node_id, day_utc)
);
```

## 6. Anomaly catalog v1

### A-001 Queue Congestion
Trigger: `queue_depth > 10` for 3 consecutive heartbeats.  
Reflex: increase telemetry interval, suppress low-priority events, mark node degraded.

### A-002 Memory Leak Suspected
Trigger: `free_heap_bytes` declines across 3+ consecutive heartbeats with no recovery above moving average.  
Reflex: reduce workload, request module status, schedule reboot if trend persists.

### A-003 Weak Connectivity
Trigger: `wifi_rssi < -80` for 5 minutes.  
Reflex: increase heartbeat interval, reduce telemetry rate, add placement advisory.

### A-004 Command Lag
Trigger: p95 command ack latency exceeds threshold.  
Reflex: pause new non-critical commands, prioritize config and health commands.

### A-005 Offline Flapping
Trigger: online/offline transition more than 3 times in 10 minutes.  
Reflex: move node to degraded, increase `offline_after_sec`, reduce message frequency.

### A-006 Auth Failure Burst
Trigger: repeated auth failures for node or source IP.  
Reflex: quarantine source, suppress provisioning route, raise security alert.

### A-007 Invalid Message Storm
Trigger: invalid envelope rate crosses threshold.  
Reflex: quarantine node, flag firmware suspect.

### A-008 Dead-Letter Growth
Trigger: `dead_letter_count` increasing over time.  
Reflex: inspect transport, back off sends, queue-drain mode.

### A-009 Duplicate Message Spike
Trigger: duplicate `message_id` detections increase sharply.  
Reflex: inspect reconnect loop, reduce retry aggressiveness.

### A-010 Fleet Hotspot
Trigger: multiple nodes in same zone show RSSI, queue, or offline anomalies.  
Reflex: zone-level alert, suspend non-critical automation in zone, recommend network inspection.

## 7. Reflex engine

### 7.1 Reflex action classes
- `observe_only`
- `emit_alert`
- `publish_config_update`
- `set_node_degraded`
- `quarantine_node`
- `throttle_node`
- `request_reboot`
- `retire_stale_commands`
- `pause_zone_automation`
- `require_human_approval`

### 7.2 Reflex safety levels
- **L0** log only
- **L1** notify only
- **L2** reversible config change
- **L3** disruptive but recoverable action
- **L4** human approval required

Default rule: nothing above L2 auto-executes unless explicitly allowlisted per zone.

### 7.3 Reflex pipeline
1. anomaly detected
2. evidence scored
3. suppression check
4. rule lookup
5. safety policy check
6. action issued
7. command/result tracked
8. recovery verification
9. anomaly resolved or escalated

## 8. Fleet scoring

### 8.1 Node health score (0–100)
Weighted model:
- reliability: 35%
- performance: 25%
- security: 20%
- maintainability: 10%
- responsiveness: 10%

Inputs include heartbeat regularity, offline transitions, duplicate rate, dead-letter count, queue depth, command lag, memory trend, auth failures, signed-message adoption, firmware drift, config drift, OTA support, and telemetry freshness.

### 8.2 Zone score
Weighted average of node health scores, anomaly concentration, correlated failures, and zone automation stability.

### 8.3 Fleet score
Weighted average of zone scores, unresolved critical anomalies, percentage of signed nodes, percentage of degraded nodes, and test/deployment conformance.

## 9. Auto-healing rules v1

### H-001 Congestion Backoff
If A-001 fires, publish `config_update` to increase telemetry and heartbeat intervals, then re-evaluate in 5 minutes.

### H-002 Leak Guard
If A-002 persists across 5 heartbeats, request low-impact reboot during safe window.

### H-003 Connectivity Saver
If A-003 fires, reduce telemetry chatter and switch node to low-bandwidth mode.

### H-004 Command Backlog Cleanup
If pending/timeout command ratio exceeds threshold, retire timed-out commands older than grace period and pause non-critical commands.

### H-005 Security Quarantine
If A-006 or A-007 fires, quarantine node or client ID and require operator review.

### H-006 Flap Dampener
If A-005 fires, suppress noisy alerts briefly, increase `offline_after_sec`, and mark node unstable.

### H-007 Zone Safeguard
If A-010 fires, pause non-critical automation in affected zone while keeping safety-critical commands enabled.

## 10. REST API additions

- `GET /api/ops/anomalies`
- `GET /api/ops/anomalies/{anomaly_id}`
- `POST /api/ops/anomalies/{anomaly_id}/acknowledge`
- `POST /api/ops/anomalies/{anomaly_id}/resolve`
- `GET /api/ops/fleet/score`
- `GET /api/ops/nodes/{node_id}/score`
- `GET /api/ops/fleet/health`
- `POST /api/ops/reflex/rules/{rule_id}/simulate`
- `POST /api/ops/reflex/actions/{action_id}/cancel`

## 11. MQTT topics

Published by gateway/ops:
- `cnp/v1/fleet/anomalies`
- `cnp/v1/fleet/health`
- `cnp/v1/nodes/{id}/ops/action`
- `cnp/v1/zones/{zone}/ops/event`

Consumed by ops:
- `cnp/v1/nodes/+/heartbeat`
- `cnp/v1/nodes/+/events`
- `cnp/v1/nodes/+/errors`
- `cnp/v1/nodes/+/ack`
- `cnp/v1/nodes/+/cmd/out`
- `cnp/v1/fleet/events`

## 12. Rule definition format

```yaml
rule_id: A-001
name: Queue Congestion
scope: node
when:
  metric: queue_depth
  operator: ">"
  value: 10
  consecutive_hits: 3
severity: warning
default_reflex:
  action_type: publish_config_update
  payload:
    telemetry_interval_sec_multiplier: 2.0
    heartbeat_interval_sec_multiplier: 1.5
suppress_for_sec: 300
requires_human_above_level: L2
```

## 13. Python module structure

```text
gateway/app/ops/
  __init__.py
  anomalies.py
  detector.py
  reflex.py
  scoring.py
  healer.py
  rules.py
  summaries.py
  api.py
  models.py
```

## 14. First implementation roadmap

### Phase O1 — Foundation
- add ops tables
- add anomaly DTOs
- add anomaly and score endpoints
- add heartbeat daily summary aggregation

### Phase O2 — Detection
- implement A-001 through A-005
- compute node score
- dashboard-ready summaries

### Phase O3 — Reflexes
- implement safe L0–L2 reflex actions
- config backoff
- quarantine integration
- stale command retirement

### Phase O4 — Healing + governance
- operator acknowledgements
- human approval workflow
- zone safeguards
- fleet score
- simulation endpoint

## 15. Testing requirements

Unit tests:
- each anomaly rule triggers correctly
- suppression windows behave correctly
- score calculations deterministic
- unsafe reflexes do not auto-execute

Integration tests:
- heartbeat stream causes anomaly creation
- anomaly triggers `config_update`
- ack closes reflex action
- failed reflex escalates
- zone anomaly pauses zone automation

Performance tests:
- anomaly engine handles 500 events/sec without falling behind
- score recomputation for 10k nodes completes within batch window
- no more than 5% additional write latency from ops instrumentation

Safety tests:
- no automatic action above policy level
- quarantined nodes remain isolated until release
- operator overrides fully audited

## 16. Success metrics

CNP-OPS-004 succeeds when:
- ≥90% of seeded anomaly scenarios are detected in tests
- <5% false positives on benchmark replay datasets
- ≥60% of recoverable congestion/connectivity incidents are resolved automatically
- anomaly detection p95 < 2s from triggering signal
- 100% of reflex actions link to anomaly and rule IDs
- every node has a current health score
- 0 unsafe auto-actions beyond policy level

## 17. How this changes Codessa

Without CNP-OPS-004, Codessa can observe and command nodes.

With CNP-OPS-004, Codessa can notice patterns, evaluate health, protect itself, reduce damage automatically, heal recoverable conditions, escalate intelligently, and learn what healthy fleet behavior looks like.

That is the transition from a managed system to a living operational intelligence network.
