# CNP v1 Starter Kit Comparative Analysis and Unification Specification

Date: 2026-03-18

## 1. Executive summary

I compared two implementations of the Codessa Node Protocol starter kit:

- **Claude version**: a monolithic, HTTP-first starter kit consisting of `cnp_node_skeleton.ino`, `gateway.py`, `node_registry.sql`, `cnp_v1_schemas.json`, and `test_flow.sh`.
- **Current system version**: the modular MQTT-first starter kit in `cnp_v1_starter_kit/`, with split firmware components, a FastAPI gateway package, registry/storage modules, documented schemas, OTA scaffolding, and helper scripts.

### Bottom line

**Claude's version is more operational today**: it is easier to run immediately, its end-to-end flow is complete, and it includes a stronger dashboard/query surface for first deployment.

**The current system version is the stronger long-term foundation**: it has a better modular architecture, better separation of concerns, persistent device identity, OTA scaffolding, richer registry semantics, and a more scalable MQTT event model.

### Best unification strategy

Do **not** pick one and discard the other.

Instead:
- keep the **current system's modular firmware, identity model, OTA abstraction, and MQTT backbone**;
- merge in **Claude's HTTP bootstrap path, richer REST endpoints, SQL views, smoke tests, and dashboard usability**;
- support **dual transport** in Unified CNP v1.1:
  - HTTP for provisioning, diagnostics, smoke testing, and ultra-simple nodes;
  - MQTT for steady-state production messaging.

The unified result should be:
- **modular on-device architecture**,
- **transport-agnostic protocol envelope**,
- **broker-backed low-latency runtime**,
- **REST-rich operator experience**,
- **clean migration path** for existing HTTP polling nodes.

---

## 2. Method used

The comparison covered:

- firmware architecture and extensibility
- gateway architecture and message flow
- schema completeness and validation rigor
- data model and registry design
- security controls
- testing and operational readiness
- measurable runtime or static metrics available in this environment

### What was validated directly

- Claude `test_flow.sh` completed successfully end-to-end against its FastAPI gateway.
- Current system schema validation script completed successfully.
- Current system JSON roundtrip benchmark completed successfully.

### What was not fully validated here

- ESP32 firmware compilation for either implementation was not performed in this environment.
- Current system MQTT runtime was not exercised end-to-end because no broker-backed integration flow was bundled for this environment.

---

## 3. Measured and observable metrics

## 3.1 Artifact size and structure

| Metric | Claude version | Current system |
|---|---:|---:|
| Total source/doc files | 6 | 43 |
| Approx. total lines | 2,039 | 2,127 |
| Gateway style | single-file | package/modules |
| Firmware style | single sketch | split classes/modules |
| Formal schema form | JSON Schema file | Markdown spec + Pydantic models |
| Database form | dedicated `.sql` file | inline schema in Python + schema docs |

Interpretation:
- Claude concentrates functionality into fewer files, which lowers initial friction.
- The current system spreads responsibility across modules, which improves maintainability and extension safety.

## 3.2 Runtime validation results

### Claude version
- End-to-end smoke test: **passed**
- Flow executed successfully: hello -> heartbeat -> telemetry event -> alert event -> error -> command issue -> poll -> command ack -> registry inspection

### Current system
- Schema validation script: **passed**
- JSON roundtrip benchmark: **mean 11.08 us/op**, **P95 17.72 us/op** for the sample event payload
- Unit test execution in this environment did not complete because Python dependencies were not preinstalled in the runner

## 3.3 Message transport implications

| Area | Claude version | Current system |
|---|---|---|
| Primary node transport | HTTP POST + GET polling | MQTT publish/subscribe |
| Command delivery model | node polls gateway | gateway pushes via broker |
| Expected command latency | bounded by poll interval | near-real-time once subscribed |
| Debuggability | very high | medium |
| Production scalability | moderate | higher |
| Infra dependency | low | moderate (needs broker) |

Interpretation:
- Claude is better for **first contact** and field debugging.
- The current system is better for **multi-node scale**, lower idle chatter, and event-driven control.

---

## 4. Architectural comparison

## 4.1 Firmware architecture

### Claude version

Characteristics:
- single `ino` file
- direct Wi-Fi + HTTP client calls
- constants edited in source for node identity and network config
- base sketch already includes registration, heartbeat, event posting, command polling, and error reporting
- developer only fills in:
  - `nodeSetup()`
  - `readSensors()`
  - `handleActuator()`

Strengths:
- very approachable
- fast to understand
- minimal indirection
- excellent for a first hardware bring-up

Weaknesses:
- protocol, transport, config, scheduling, and node logic are tightly coupled
- identity is source-defined rather than persisted from device UID
- harder to add alternative transports or policy layers without editing core logic
- OTA is not implemented as a first-class subsystem
- queueing is present but relatively shallow and embedded in the sketch

### Current system

Characteristics:
- application core plus distinct subsystems:
  - `ConfigManager`
  - `IdentityManager`
  - `EventQueue`
  - `Protocol`
  - `TransportMqtt`
  - `OtaManager`
  - `BaseModule`
- derived modules implement a stable interface instead of editing protocol code
- device UID and generated node ID are persisted in NVS via `Preferences`

Strengths:
- much better separation of concerns
- base framework is reusable across node families
- persistent identity is production-grade behavior
- queueing, protocol, module logic, and OTA are independently evolvable
- aligns with the user's long-term Codessa node platform vision

Weaknesses:
- more pieces to understand
- higher bring-up complexity
- some parts are scaffold-level rather than fully finished, especially time sync and some lifecycle handling

### Firmware verdict

- **Claude wins on simplicity and immediate usability.**
- **Current system wins on architectural quality, extensibility, and long-term maintainability.**

---

## 4.2 Gateway architecture

### Claude version

Characteristics:
- one FastAPI file
- SQLite-backed
- direct HTTP ingestion endpoints for nodes
- direct dashboard endpoints
- background offline watcher
- command queue stored in DB and served via polling endpoint
- Memory Bridge Hook explicitly placed in code

Strengths:
- operationally complete
- easy to run and inspect
- API surface is practical and already dashboard-friendly
- fewer moving parts for local deployment

Weaknesses:
- monolithic gateway will accumulate technical debt as features expand
- synchronous SQLite access in a large single file is harder to evolve safely
- transport and persistence are tightly coupled to REST handlers
- token auth is globally static and minimal

### Current system

Characteristics:
- modular FastAPI package
- dedicated modules for:
  - config
  - DB schema init
  - registry updates
  - storage operations
  - MQTT bridge
  - API routes
  - Pydantic schemas
- MQTT bridge is the message ingress/egress core
- REST layer is currently thin

Strengths:
- cleaner boundaries
- easier to test and replace subsystems
- better fit for scale-out and future broker-backed routing
- more natural place to insert Codessa orchestration, Memory Cortex routing, and policy engines

Weaknesses:
- REST/operator surface is incomplete compared with Claude
- missing the richer introspection endpoints needed for immediate operations
- no bundled end-to-end integration test flow matching its broker-based design

### Gateway verdict

- **Claude wins on operational completeness today.**
- **Current system wins on internal architecture and future extensibility.**

---

## 4.3 Message schema and protocol design

### Claude version

Characteristics:
- one JSON Schema file with definitions for major packet types
- field naming is friendly and pragmatic
- schema examples included
- message envelope is simpler, but not as strict as current system's modeled envelope

Strengths:
- portable contract for multiple clients
- easy to hand to another agent or service
- pairs well with the smoke-test script

Weaknesses:
- envelope naming is inconsistent with current system (`protocol` / `timestamp` in some flow examples vs `protocol_version` / `ts_utc` elsewhere)
- command/event payload names are more ad hoc (`params`, `data`)
- acknowledgment model is lighter

### Current system

Characteristics:
- detailed message spec with topic bindings and validation rules
- shared envelope fields are clearer and more formal
- Pydantic models provide typed validation in the gateway
- explicit ack model and delivery semantics
- includes `config_update`, `ack`, `requires_ack`, `delivery_mode`

Strengths:
- better basis for interoperability and future signing/HMAC
- clearer distinction between message ID, correlation ID, and payload details
- stronger semantic basis for transport-agnostic design

Weaknesses:
- documentation/schema split across Markdown spec and code model instead of one machine-readable JSON Schema artifact
- timestamps currently degrade at firmware side because `nowUtc()` is still placeholder logic

### Schema verdict

- **Claude wins on portability of a single machine-readable schema file.**
- **Current system wins on protocol rigor and future-proof semantics.**

---

## 4.4 Data model and registry design

### Claude version

Tables:
- `nodes`
- `events`
- `commands`
- `heartbeats`
- `errors`
- `node_config`

Views:
- `v_node_status`
- `v_recent_alerts`
- `v_pending_commands`
- `v_event_summary`

Strengths:
- highly practical
- heartbeats retained separately from node table
- self-trimming heartbeat trigger prevents unbounded growth
- views are dashboard-ready
- config table is a clean operator control surface

Weaknesses:
- less rich node metadata than current system
- no dedicated ack table
n- device UID not modeled in the schema
- fewer fields for OTA, config versions, queue depth, heap, hardware model, tags, metadata

### Current system

Tables:
- `nodes`
- `events`
- `commands`
- `errors`
- `acks`

Strengths:
- stronger identity model (`device_uid`)
- richer operational metadata
- more future-ready for fleet management and OTA
- explicit ack persistence is valuable for delivery guarantees and auditability

Weaknesses:
- no dedicated heartbeat history table
- no retention policy or trigger for logs
- no prebuilt views for dashboards
- no separate node config table yet

### Registry verdict

- **Claude wins on operator usability and storage hygiene.**
- **Current system wins on fleet metadata richness and protocol completeness.**

---

## 4.5 Testing and developer experience

### Claude version

Strengths:
- best-in-class smoke-test path for this phase
- `test_flow.sh` exercises the full lifecycle with no hardware
- very easy to demo and validate locally

Weaknesses:
- limited automated unit testing structure
- no benchmark harness included

### Current system

Strengths:
- includes validation and benchmark scripts
- has a package layout suitable for unit/integration test expansion
- includes a pytest test file

Weaknesses:
- current tests do not yet cover full message flow
- no broker-backed integration harness included
- first-run experience is weaker than Claude's

### Testing verdict

- **Claude wins on end-to-end usability.**
- **Current system wins on test architecture direction, but not yet on execution completeness.**

---

## 4.6 Security comparison

### Claude version

Implemented:
- simple token check via `X-CNP-Token`
- command logging
- separation between node and operator endpoints

Gaps:
- single shared token set in gateway source
- no per-node credentials
- no signature or HMAC validation
- no TLS assumptions encoded
- permissive CORS (`*`)
- HTTP payloads are trusted after token acceptance

### Current system

Implemented:
- envelope includes optional signature field
- stronger message structure supports future signing
- persistent identity via `device_uid`
- OTA subsystem exists and can be extended to signed manifests

Gaps:
- no actual auth enforcement in the current gateway path
- no broker ACL model in the starter kit
- no signature verification logic yet
- no cert pinning or signed OTA manifests

### Security verdict

- **Claude is slightly safer today in practice** because it actually enforces a token.
- **Current system is better positioned architecturally** for stronger security, but currently leaves more of it as planned work.

---

## 5. Gap analysis matrix

| Domain | Claude stronger | Current system stronger | Gap / risk | Recommendation |
|---|---|---|---|---|
| Firmware simplicity | Yes | No | Current system harder for first node bring-up | Keep modular core, add Claude-style quickstart wrappers |
| Persistent identity | No | Yes | Claude nodes can drift or duplicate if source constants are copied | Standardize device UID + generated node ID across both |
| OTA support | No | Yes | Claude lacks upgrade pathway | Merge current `OtaManager` into unified firmware |
| Transport scalability | No | Yes | Claude polling increases chatter and command latency | Keep MQTT runtime, add HTTP compatibility adapter |
| Immediate operability | Yes | No | Current system lacks comparable end-to-end smoke test | Port Claude `test_flow.sh` into unified CI/dev flow |
| REST dashboard API | Yes | No | Current system too thin for operators | Import Claude endpoints and SQL views |
| Schema rigor | Moderate | Yes | Claude field naming drift can cause incompatibility | Create canonical envelope and add alias mapping |
| Machine-readable schema | Yes | Partial | Current system docs not enough for external implementers | Export JSON Schema from unified models |
| DB metadata richness | No | Yes | Claude schema weaker for fleet management | Extend unified `nodes` table with current metadata fields |
| Heartbeat history retention | Yes | No | Current system can grow unbounded / lacks trend table | Add heartbeat table + trim trigger |
| Ack tracking | No | Yes | Claude loses explicit delivery audit detail | Keep current ack table and command-result detail |
| Security enforcement | Yes | Planned | Current system auth incomplete | Implement per-node credentials and HMAC verification |
| Code modularity | No | Yes | Claude gateway will accrue debt faster | Refactor gateway into services while preserving endpoint behavior |
| Testing completeness | Yes | Partial | Current system lacks a no-broker full integration test | Build dual test harness: HTTP smoke + MQTT integration |

---

## 6. Technical debt assessment

## 6.1 Claude version technical debt

1. **Monolithic gateway file**
   - risk: growing feature set becomes fragile
   - impact: medium-high

2. **Source-defined node identity**
   - risk: duplicated IDs and brittle provisioning
   - impact: high

3. **Polling-based command path**
   - risk: latency and unnecessary network traffic
   - impact: medium

4. **Minimal auth model**
   - risk: token leakage compromises fleet
   - impact: high

5. **Tight coupling of protocol and transport in firmware**
   - risk: hard to evolve to MQTT, BLE gatewaying, or offline queueing
   - impact: high

## 6.2 Current system technical debt

1. **Incomplete operator-facing REST surface**
   - risk: hard to deploy and inspect
   - impact: high

2. **No bundled broker-backed integration test**
   - risk: architectural intent not operationally proven
   - impact: high

3. **Schema split across docs and code**
   - risk: contract drift for external implementers
   - impact: medium

4. **Placeholder firmware time source**
   - risk: incorrect timestamps and event ordering
   - impact: high

5. **Auth/signature model not implemented**
   - risk: better designed than enforced
   - impact: high

---

## 7. Strategic roadmap for unification

## Phase 0: Stabilization and compatibility definition

Priority: Critical

Deliverables:
- define **canonical Unified CNP envelope**
- publish field alias map for backward compatibility
- freeze v1 compatibility matrix
- identify all node and gateway behaviors that must remain supported

### Compatibility map

| Claude field/style | Unified canonical field |
|---|---|
| `protocol` | `protocol_version` |
| `timestamp` | `ts_utc` |
| `params` | `arguments` |
| `data` | `body` |
| `event_id` | keep as payload field for human traceability, but use `message_id` as canonical transport identifier |

## Phase 1: Gateway merge

Priority: Critical

Actions:
- keep the current modular gateway package layout
- port Claude REST endpoints into modular route/service files
- add SQL views and node config table
- add heartbeat history table and trim trigger
- add a compatibility ingestion adapter for Claude HTTP messages

Result:
- same easy operator experience as Claude
- better internal architecture than Claude

## Phase 2: Firmware merge

Priority: Critical

Actions:
- keep current modular firmware classes
- add optional HTTP transport alongside MQTT transport
- add a `QuickNodeModule` template that feels as simple as Claude's three-function model
- use persistent device UID + generated node ID universally
- merge Claude's direct usability patterns into the modular framework

Result:
- derived nodes still only implement sensor and actuator logic
- platform remains extensible and production-oriented

## Phase 3: Security hardening

Priority: High

Actions:
- per-node credentials instead of one shared token
- HMAC signature verification using `sig`
- broker ACLs by topic prefix
- signed OTA manifests and channel policy
- TLS requirements for gateway and OTA URLs
- role separation between operator API and node API

## Phase 4: Observability and memory integration

Priority: High

Actions:
- implement Memory Bridge abstraction from both versions
- stream meaningful events into Memory Cortex / Supabase
- add node health dashboards from registry views
- add alert summarization and incident feeds

## Phase 5: Scale and resilience

Priority: Medium

Actions:
- add command retries and timeout sweeper
- add dead-letter queue for malformed messages
- add event retention policies
- add broker reconnect test scenarios
- add fleet-level provisioning and config rollout support

---

## 8. Merge conflict resolution strategy

## 8.1 Principle

Prefer **behavior preservation** over line-by-line merging.

That means:
- keep current system packages and classes
- re-express Claude behavior inside those modules
- do not merge monolithic files into modular packages directly

## 8.2 Rules

1. **Protocol semantics come from the current system.**
2. **Operator workflows come from Claude unless they conflict with protocol rigor.**
3. **Database schema becomes additive, not substitutive.**
4. **Transport remains pluggable.**
5. **Existing HTTP node behavior must continue working through a compatibility adapter.**

## 8.3 Concrete merge approach

- Create `gateway/app/api/http_compat.py` for Claude-style node endpoints.
- Create `gateway/app/services/commands.py`, `events.py`, `nodes.py`, `config.py`.
- Move Claude SQL views into `gateway/app/core/db.py` schema migration layer.
- Add `TransportHttp` to firmware next to `TransportMqtt`.
- Add message translation utilities:
  - Claude HTTP payload -> canonical CNP envelope
  - canonical command -> Claude poll response shape if legacy mode enabled

---

## 9. Backward compatibility preservation plan

## 9.1 Node compatibility tiers

### Tier A: Legacy Claude HTTP nodes
Supported via:
- `/api/node/hello`
- `/api/node/heartbeat`
- `/api/node/event`
- `/api/node/state`
- `/api/node/error`
- `/api/node/commands/{node_id}`
- `/api/node/command_result`

### Tier B: Unified CNP nodes over HTTP
Supported via canonical envelope on REST endpoints.

### Tier C: Unified CNP nodes over MQTT
Preferred production mode.

## 9.2 Deprecation policy

- keep Claude-style payload aliases for at least one minor protocol cycle
- emit warnings in gateway logs for deprecated fields
- provide migration linter and firmware config flag `legacy_http_mode`

## 9.3 Data migration policy

- preserve existing node IDs
- backfill `device_uid` as nullable until nodes re-register
- keep old command rows and ack status mapping
- transform heartbeat rows into history table without losing status trends

---

## 10. Unified system architecture specification

## 10.1 Architecture overview

```text
Node Module (sensor/actuator logic)
        |
   Base Firmware Runtime
   - IdentityManager
   - ConfigManager
   - EventQueue
   - Protocol
   - TransportHttp / TransportMqtt
   - OtaManager
        |
   Unified CNP Envelope
        |
   Gateway Ingress Layer
   - HTTP compatibility adapter
   - Canonical REST ingest
   - MQTT bridge
        |
   Gateway Services
   - registry
   - event storage
   - command service
   - error/ack tracking
   - config service
   - memory bridge
        |
   SQLite / Postgres / Supabase
        |
   Codessa Core / Memory Cortex / Dashboard
```

## 10.2 Unified data model

### `nodes`
Required fields:
- `node_id`
- `device_uid`
- `node_name`
- `node_type`
- `protocol_version`
- `firmware_version`
- `hardware_model`
- `capabilities_json`
- `config_version`
- `status`
- `last_seen_utc`
- `first_seen_utc`
- `boot_reason`
- `heartbeat_interval_sec`
- `offline_after_sec`
- `last_rssi`
- `battery_pct`
- `free_heap_bytes`
- `queue_depth`
- `supports_ota`
- `ota_channel`
- `ota_last_result`
- `tags_json`
- `metadata_json`

### `heartbeats`
Add to unified schema:
- `id`
- `node_id`
- `status`
- `uptime_sec`
- `battery_pct`
- `wifi_rssi`
- `free_heap_bytes`
- `queue_depth`
- `received_at`

Retention:
- trim to last N heartbeats per node, configurable, default 500

### `events`
Keep canonical fields:
- `message_id`
- `node_id`
- `ts_utc`
- `category`
- `event_type`
- `priority`
- `requires_ack`
- `body_json`
- optional `legacy_event_id`

### `commands`
Keep canonical command fields plus compatibility metadata:
- `command_id`
- `node_id`
- `command_type`
- `category`
- `issued_by`
- `issued_ts_utc`
- `status`
- `timeout_ms`
- `arguments_json`
- `result_code`
- `result_details_json`
- `completed_ts_utc`
- `delivery_transport`

### `errors`
Keep:
- `message_id`
- `node_id`
- `ts_utc`
- `severity`
- `domain`
- `code`
- `message`
- `recoverable`
- `diagnostics_json`

### `acks`
Keep explicit ack records for delivery tracing.

### `node_config`
Merge Claude's concept into unified schema:
- `node_id`
- `config_version`
- `heartbeat_interval_sec`
- `telemetry_interval_sec`
- `offline_after_sec`
- `permissions_json`
- `transport_preference`
- `module_config_json`
- `updated_at`

## 10.3 Unified API specification

### Node-facing REST endpoints
- `POST /api/node/hello`
- `POST /api/node/heartbeat`
- `POST /api/node/event`
- `POST /api/node/state`
- `POST /api/node/error`
- `POST /api/node/command_result`
- `GET /api/node/commands/{node_id}`

### Canonical operator endpoints
- `GET /api/health`
- `GET /api/nodes`
- `GET /api/nodes/{node_id}`
- `GET /api/events`
- `GET /api/alerts`
- `GET /api/commands`
- `POST /api/nodes/{node_id}/commands`
- `PATCH /api/nodes/{node_id}/config`
- `POST /api/nodes/{node_id}/ota`
- `GET /api/metrics/summary`

### MQTT topics
- `cnp/v1/nodes/{node_id}/hello`
- `cnp/v1/nodes/{node_id}/heartbeat`
- `cnp/v1/nodes/{node_id}/state`
- `cnp/v1/nodes/{node_id}/events`
- `cnp/v1/nodes/{node_id}/errors`
- `cnp/v1/nodes/{node_id}/ack`
- `cnp/v1/nodes/{node_id}/cmd/in`
- `cnp/v1/nodes/{node_id}/cmd/out`
- `cnp/v1/nodes/{node_id}/config`

## 10.4 Unified firmware contract

Derived project authors should only implement:
- `begin()` or equivalent node init
- `appendTelemetry()` / sensor acquisition
- `handleCommand()` / actuator handling
- optional module-specific config application

The base runtime owns:
- identity persistence
- transport connection and retries
- registration and ack handling
- heartbeat scheduling
- event queueing and retries
- command decoding and response envelope creation
- error formatting
- OTA lifecycle

---

## 11. Testing requirements for the unified system

## 11.1 Minimum automated tests

### Contract tests
- validate all packet types against machine-readable schema
- validate alias mapping from Claude fields to canonical fields
- reject invalid signatures, categories, priorities, and command statuses

### Gateway tests
- node registration upsert
- heartbeat updates and offline marking
- event insert and alert filtering
- command enqueue and result update
- compatibility endpoint translation
- config patch and version increment

### Firmware tests
- identity persistence across reboot
- event queue replay after connection loss
- command parse and validation
- OTA dry-run and failure handling

### Integration tests
- HTTP legacy flow end-to-end
- MQTT native flow end-to-end
- mixed fleet operation (legacy HTTP + native MQTT)
- offline/reconnect behavior
- command timeout behavior

### Performance tests
- gateway ingest throughput under 100, 500, 1000 msgs/sec simulated load
- command latency p50/p95 for MQTT and HTTP polling modes
- storage growth over 24h simulated heartbeat flood with retention enabled

## 11.2 Benchmarks to record

- `hello` ingest latency
- `event` ingest latency
- command delivery latency
- offline detection delay
- DB size growth per 10k events
- memory usage on gateway process
- firmware heap watermark under sustained publish/load

---

## 12. Deployment procedures

## 12.1 Local development deployment

1. start MQTT broker
2. initialize gateway DB schema
3. run gateway API
4. run HTTP smoke tests
5. run MQTT integration tests
6. flash a reference node
7. confirm node registration in dashboard endpoints

## 12.2 Edge lab deployment

1. provision per-node credentials
2. assign node config profile
3. pin OTA channel and manifest source
4. enable metrics and alert views
5. connect memory bridge to Codessa Memory Cortex / Supabase

## 12.3 Production deployment

1. move DB from SQLite to managed Postgres/Supabase where appropriate
2. enforce TLS and broker ACLs
3. enable signed OTA and rollback policy
4. add structured logs and metrics export
5. enable retention jobs and archiving

---

## 13. Success metrics for the merged system

## Functional success
- one reference node can be deployed without editing core framework code
- legacy Claude HTTP nodes continue to operate
- native MQTT nodes operate with push-based commands
- all major message types are persisted and queryable

## Reliability success
- nodes are marked offline within configured timeout + watcher interval
- queued events are retried and acknowledged correctly
- command results always reconcile to a stored command row
- OTA failures do not brick the node and are recorded

## Maintainability success
- firmware transport can be swapped without editing module logic
- gateway endpoints can evolve without touching storage primitives
- machine-readable schema stays generated from canonical models
- test suite covers both compatibility and native paths

## Performance success
- p95 MQTT command delivery materially lower than HTTP polling mode
- gateway handles target fleet load without dropped messages
- retention controls prevent unbounded heartbeat table growth
- dashboard queries return within operator-friendly latency targets

---

## 14. Final recommendation

### Adopt this unification decision

**Use the current system as the structural base.**

Then merge in Claude's strengths aggressively:
- full smoke-test lifecycle
- node-friendly HTTP onboarding path
- richer SQL views
- operator REST endpoints
- practical first-deployment ergonomics

### Priority order

1. merge gateway operator features and HTTP compatibility
2. merge heartbeat history + retention controls
3. keep modular firmware and add HTTP transport adapter
4. unify schema into canonical models with generated JSON Schema
5. implement real security instead of placeholder security
6. add dual integration test harnesses

### Plain-English conclusion

Claude built the **better demoable product surface**.
The current system built the **better platform core**.

The best unified Codessa network is:
- **Claude outside** for ease of use,
- **current system inside** for scale, rigor, and longevity.

