**CODESSA NODE PROTOCOL v1**

Unified System Technical Specification

| Document No. | CNP-SPEC-001 |
| :---- | :---- |
| Version | 1.0 |
| Status | Final Draft |
| Date | March 2026 |
| Author | Codessa Systems — Architecture Team |
| Classification | Internal — Confidential |

# **Table of Contents**

# **Executive Summary**

This document presents a comprehensive comparative analysis between two independently developed implementations of the Codessa Node Protocol v1 (CNP v1): the Current System (CS, herein "V1") generated as a rapid-development starter kit, and the Uploaded System (US, herein "V2") delivered as a production-oriented reference architecture. The analysis covers all layers of both systems — transport, firmware, gateway, persistence, security, and operations — and culminates in a strategic roadmap and full technical specification for a Unified System (US+) that incorporates the best of both implementations.

The central finding is that V2 is architecturally superior in every structural dimension: it uses MQTT over HTTP polling, a modular C++ firmware with proper object-oriented design, PlatformIO over Arduino IDE, Pydantic v2 validation, async database access, a richer protocol envelope, and a production-grade OTA abstraction. V1's primary contribution is rapid-path HTTP accessibility, clear procedural logic for onboarding developers unfamiliar with MQTT, and a companion SQL schema with helper views that V2 does not replicate. The Unified System (US+) adopts V2 as its canonical architecture and integrates V1's HTTP compatibility layer, SQL views, and curl-based test tooling.

# **Scope and System Definitions**

## **System V1 — Current Generated Kit**

V1 is a self-contained starter kit delivered as a single .ino sketch (Arduino IDE), a single-file Python FastAPI gateway (gateway.py), and a SQLite schema SQL file. Transport is HTTP POST with polling-based command retrieval. There is no test suite, no schema validation library, and no MQTT integration.

## **System V2 — Uploaded Production Kit**

V2 is a production-oriented kit comprising a modular C++ firmware project (PlatformIO, 9 headers, 9 source files), a properly layered Python gateway package (FastAPI, asyncio-mqtt, Pydantic v2, aiosqlite, orjson), a formal schema specification, a pytest suite, a benchmark script, and deployment documentation.

## **Unified System (US+)**

US+ is the proposed merged architecture that adopts V2 as its canonical implementation, incorporates V1's HTTP compatibility adapter as a legacy-accessible gateway shim, preserves V1's SQL view layer, and adds explicit test coverage, migration tooling, and CI pipeline scaffolding.

# **Architecture Comparison**

## **Transport Layer**

| Dimension | V1 (Current) | V2 (Uploaded) | Advantage |
| :---- | :---- | :---- | ----- |
| Primary transport | HTTP REST (synchronous POST) | MQTT pub/sub (async) | **V2 Superior** |
| Command delivery | HTTP GET poll every \~5s | MQTT topic push (instant) | **V2 Superior** |
| Latency (command) | 2.5–5 s average | \<200 ms typical | **V2 Superior** |
| Broker dependency | None (direct to gateway) | MQTT broker required | **V1 Only** |
| Multi-node fan-out | O(n) HTTP connections | O(1) broker subscription | **V2 Superior** |
| Offline buffering | None (fire and forget) | QoS 1 \+ client queue | **V2 Superior** |
| TLS support | Not implemented | Hook present, add certs | **V2 Superior** |
| Dev friendliness | curl-testable instantly | Requires broker setup | **V1 Only** |

## **Protocol Envelope**

| Field | V1 Envelope | V2 Envelope | Delta |
| :---- | :---- | :---- | ----- |
| protocol | "CNPv1" | protocol\_version: "CNPv1" | Key renamed |
| message\_id | Absent | message\_id (ULID, len 20–36) | **V2 Only** |
| qos | Absent | qos: 0|1 | **V2 Only** |
| correlation\_id | Absent | correlation\_id (optional) | **V2 Only** |
| sig | Absent | sig (optional HMAC) | **V2 Only** |
| timestamp | timestamp | ts\_utc | Key renamed |
| payload | Present | Present | **Both** |

## **Firmware Architecture**

| Dimension | V1 | V2 | Advantage |
| :---- | :---- | :---- | ----- |
| Design pattern | Procedural single-file .ino | OOP: Application \+ BaseModule | **V2 Superior** |
| Build system | Arduino IDE | PlatformIO (pio) | **V2 Superior** |
| Config storage | \#define constants | NVS via ConfigManager | **V2 Superior** |
| Identity | Rebuilt each flash | IdentityManager \+ device\_uid | **V2 Superior** |
| Message queuing | None | EventQueue with retries | **V2 Superior** |
| OTA | Not present | OtaManager abstraction | **V2 Only** |
| Custom node modules | Edit monolith | Subclass BaseModule | **V2 Superior** |
| Protocol separation | Inline in loop() | Dedicated Protocol class | **V2 Superior** |
| Timestamp | Uptime-derived stub | Requires NTP (documented) | **Both** |
| Dependencies | ArduinoJson only | ArduinoJson \+ PubSubClient | **V2 Superior** |

## **Gateway Architecture**

| Dimension | V1 | V2 | Advantage |
| :---- | :---- | :---- | ----- |
| File structure | Single gateway.py | Layered package (api/core/models) | **V2 Superior** |
| Input validation | Raw dict access | Pydantic v2 Envelope model | **V2 Superior** |
| DB access | Sync sqlite3 | Async aiosqlite | **V2 Superior** |
| MQTT bridge | Not present | GatewayMqttBridge (asyncio) | **V2 Only** |
| Config | Hardcoded constants | Environment vars / Settings | **V2 Superior** |
| HTTP auth | X-CNP-Token header | Not implemented in V2 REST | Neither complete |
| SQL views | 4 helper views | Not present | **V1 Only** |
| Heartbeat trim | AFTER INSERT trigger | Separate offline watcher | **Both** |
| Error classification | error\_code (flat) | severity \+ domain \+ code | **V2 Superior** |
| Test suite | None | pytest (test\_api.py) | **V2 Only** |
| Benchmark | None | benchmark\_gateway.py | **V2 Only** |

## **Database Schema**

| Table / Feature | V1 | V2 | Advantage |
| :---- | :---- | :---- | ----- |
| nodes columns | 15 columns | 24 columns | **V2 Superior** |
| device\_uid | Absent | Present (immutable UID) | **V2 Only** |
| hardware\_model | Absent | Present | **V2 Only** |
| boot\_reason | Absent | Present | **V2 Only** |
| config\_version | Absent | Present | **V2 Only** |
| free\_heap\_bytes | Absent | Present | **V2 Only** |
| queue\_depth | Absent | Present | **V2 Only** |
| OTA columns | Absent | supports\_ota, ota\_channel, ota\_last\_result | **V2 Only** |
| tags\_json / metadata\_json | Absent | Present (extensible) | **V2 Only** |
| acks table | Absent | Present | **V2 Only** |
| FK constraints | None (in db.py) | Present in schema docs | **V2 Superior** |
| Node status states | 3 (online/offline/degraded) | 7 (includes unknown/blocked/retired) | **V2 Superior** |
| SQL helper views | 4 views present | Absent | **V1 Only** |
| Heartbeat trim trigger | AFTER INSERT trigger | Watcher task (no trigger) | **Both** |

# **Gap Analysis Matrix**

The following matrix enumerates every identified discrepancy, classifying each by severity, technical debt class, and recommended disposition for US+.

| ID | Area | Gap Description | Severity | Disposition |
| :---- | :---- | :---- | ----- | :---- |
| G-01 | Transport | V1 HTTP polling creates 5s command latency and O(n) connection overhead | **High** | Adopt V2 MQTT; provide V1 HTTP as opt-in adapter |
| G-02 | Envelope | V1 lacks message\_id — prevents deduplication and message tracing | **Critical** | Mandate message\_id (ULID) in US+ |
| G-03 | Envelope | V1 lacks qos field — QoS is implicit and unenforceable | **High** | Add qos to all envelopes in US+ |
| G-04 | Envelope | V1 key names differ (protocol vs protocol\_version, timestamp vs ts\_utc) | **High** | Standardise to V2 names; emit V1 aliases in compat shim |
| G-05 | Firmware | V1 monolithic .ino prevents multi-node firmware reuse without copy-paste | **Critical** | Adopt V2 BaseModule pattern; port V1 example as ExampleClimateModule |
| G-06 | Firmware | V1 has no persistent identity — node\_id regenerates on reflash | **High** | Adopt V2 IdentityManager \+ NVS Preferences |
| G-07 | Firmware | V1 has no event queue — messages lost on transient send failure | **High** | Adopt V2 EventQueue |
| G-08 | Firmware | V1 has no OTA — firmware updates require physical access | **Medium** | Adopt V2 OtaManager abstraction |
| G-09 | Gateway | V1 gateway has no input validation — malformed messages crash or silently corrupt DB | **Critical** | Adopt V2 Pydantic Envelope model |
| G-10 | Gateway | V1 uses sync sqlite3 — blocks asyncio event loop under load | **High** | Adopt V2 aiosqlite throughout |
| G-11 | Gateway | V1 has no MQTT bridge — cannot receive push-model data | **High** | Adopt V2 GatewayMqttBridge |
| G-12 | Gateway | V1 gateway lacks HTTP auth in V2 — V2 drops the X-CNP-Token check | **Medium** | US+ adds per-node token validation in Pydantic middleware |
| G-13 | Database | V1 nodes table is missing 9 columns present in V2 | **High** | Apply migration DDL to add columns; set defaults |
| G-14 | Database | V1 missing acks table — acknowledgment receipts are untracked | **High** | Add acks table per V2 schema |
| G-15 | Database | V2 missing SQL helper views from V1 | **Low** | Port V1 views to US+ schema; update column refs |
| G-16 | Database | V1 errors table is flat (error\_code); V2 adds severity \+ domain | **Medium** | Migrate to V2 error model; add mapping shim for V1 consumers |
| G-17 | Events | V1 events lack requires\_ack, event\_seq, delivery\_mode fields | **High** | Add fields; default requires\_ack=false for backward compat |
| G-18 | Commands | V1 uses params; V2 uses arguments — breaking name divergence | **High** | Standardise to arguments; translate in V1 compat shim |
| G-19 | Commands | V1 commands lack dry\_run and issued\_by fields | **Medium** | Add fields; default dry\_run=false, issued\_by="system" |
| G-20 | Commands | V1 command delivery is polling; latency unacceptable for actuators | **High** | Resolved by G-01 MQTT adoption |
| G-21 | Security | Neither system implements per-node secrets or MQTT TLS in production | **Critical** | US+ adds per-node secret column; TLS config documented |
| G-22 | Testing | V1 has zero automated tests | **High** | Adopt V2 pytest suite; expand to 80%+ coverage target |
| G-23 | Testing | V1 test\_flow.sh is manual curl — not in CI | **Medium** | Convert to pytest integration test using httpx |
| G-24 | Config | V1 config in \#defines requires reflash to change | **High** | Adopt V2 NVS ConfigManager \+ config\_update MQTT message |
| G-25 | Heartbeat | V1 heartbeat lacks seq, free\_heap\_bytes, queue\_depth fields | **Medium** | Add fields per V2 spec; gateways handle missing fields gracefully |
| G-26 | Hello | V1 hello lacks device\_uid, hardware\_model, boot\_reason, supports\_ota | **High** | Add fields per V2 spec |

# **Feature Superiority Analysis**

## **Areas Where V2 Demonstrates Superior Functionality**

* **MQTT Transport Architecture.** V2's pub/sub model eliminates the fundamental O(n) HTTP polling overhead of V1. With MQTT QoS 1, commands are pushed to nodes in under 200 ms. The broker acts as a durable message store, meaning commands survive transient node disconnections — something V1 cannot achieve.

* **Modular Firmware Design.** V2's BaseModule virtual interface creates a clean extension contract. Adding a new sensor type requires only implementing four methods (name, begin, loop, appendTelemetry, handleCommand) without touching any protocol or transport code. V1 requires editing the monolith and risks breaking existing protocol logic.

* **Persistent Identity.** V2's IdentityManager stores node\_id and device\_uid in ESP32 NVS across reboots and reflashes. V1 reconstructs identity from a hardcoded \#define, meaning a reflash with a different compile target silently creates a duplicate registration with no way to reconcile historical data.

* **Event Queue with Retry.** V2's EventQueue persists outgoing messages in RAM and retries on transport failure. V1 silently drops events on WiFi interruption. For IoT reliability, especially in Codessa's physical-world sensing use case, this is not a quality-of-life feature — it is a correctness requirement.

* **Pydantic v2 Schema Validation.** V2's Envelope Pydantic model with @field\_validator catches malformed messages at the API boundary with structured error responses. V1 accesses .get() on raw dicts without any type checking, creating silent data corruption risks.

* **Richer Error Classification.** V2's three-axis error model (severity, domain, code) with a structured naming convention ({DOMAIN}\_{CLASS}\_{NUMBER}) enables programmatic error routing, alerting thresholds, and machine-readable diagnostics. V1's flat error\_code string is human-readable only.

* **OTA Firmware Update Abstraction.** V2's OtaManager provides a clean hook for HTTPS OTA updates, with an ota\_channel and ota\_last\_result tracked in the node registry. V1 has no OTA capability whatsoever, requiring physical access for every firmware update — a critical operational gap at scale.

* **Configuration Management.** V2's ConfigManager \+ NVS stores runtime configuration (MQTT host, heartbeat interval, telemetry interval) that can be updated over-the-air via config\_update messages without reflashing. V1 requires a code change and reflash for any config adjustment.

## **Areas Where V1 Maintains Advantages**

* **Zero-dependency Developer Onboarding.** V1 requires only Python \+ curl to run a complete node lifecycle test via test\_flow.sh. V2 requires MQTT broker setup (Mosquitto), PlatformIO toolchain, and asyncio-mqtt. For contributors unfamiliar with IoT infrastructure, V1's HTTP model provides a dramatically shorter path to first success.

* **SQL Helper Views.** V1's node\_registry.sql defines four production-quality views (v\_node\_status, v\_recent\_alerts, v\_pending\_commands, v\_event\_summary) that are absent from V2. These views power a dashboard without requiring application-layer aggregation queries.

* **Heartbeat Trimming Trigger.** V1's AFTER INSERT trigger that limits heartbeats to 500 per node is a self-managing retention policy that requires no application code. V2's offline watcher runs every 15s but does not manage heartbeat table size.

* **Integrated Auth Token.** V1's X-CNP-Token header check provides a baseline token gate on every HTTP endpoint. V2's REST API has no auth at all on read endpoints, relying on network-level access control that is not documented.

* **Complete End-to-End Test Script.** V1's test\_flow.sh covers the full lifecycle (hello → heartbeat → telemetry → alert → error → command issue → poll → ack → registry inspect) in 65 lines of portable shell. V2's pytest suite covers only the health endpoint.

# **Strategic Roadmap for System Unification**

The unification strategy follows a "strangler fig" pattern: V2 becomes the canonical system, V1's unique contributions are ported in, and a compatibility adapter allows existing V1 HTTP clients to continue operating during transition.

## **Phase 1 — Foundation Merge (Week 1–2)**

| Goal | V2 codebase extended with V1's SQL views, auth token middleware, and heartbeat trim logic. All existing V2 tests pass. |
| :---- | :---- |

| Task | Priority | Owner | Description |
| :---- | ----- | :---- | :---- |
| Port V1 SQL views to V2 schema | **High** | Backend | Add v\_node\_status, v\_recent\_alerts, v\_pending\_commands, v\_event\_summary to db.py SCHEMA\_SQL; update column refs to V2 names (ts\_utc, body\_json, arguments\_json) |
| Add token auth middleware | **High** | Backend | Add X-CNP-Node-Token header validation in FastAPI middleware; store per-node secrets in nodes table (new column: node\_secret\_hash) |
| Add heartbeat trim logic | **Medium** | Backend | Add AFTER INSERT trigger to heartbeats table in V2 schema, capped at 1000 rows per node |
| Expand pytest coverage | **High** | Backend | Add tests for /nodes, /nodes/{id}, /nodes/{id}/commands, and the MQTT bridge message handlers; target 60%+ coverage |

## **Phase 2 — Protocol Unification (Week 3–4)**

| Goal | Single canonical envelope spec (V2 format). V1 HTTP compatibility adapter deployed alongside V2 gateway. Migration DDL for existing V1 databases. |
| :---- | :---- |

| Task | Priority | Owner | Description |
| :---- | ----- | :---- | :---- |
| Implement HTTP compat adapter | **High** | Backend | New FastAPI router at /v1/compat/\* that accepts V1 envelope format (protocol, timestamp, params) and translates to V2 before storage. Allows existing V1 nodes to function without reflash. |
| Write V1 → V2 migration DDL | **High** | Backend | ALTER TABLE scripts adding 9 V2 columns to existing nodes table with safe defaults. Include data migration for status values (map old 3-state to new 7-state). |
| Update Pydantic model for V1 aliases | **Medium** | Backend | Add model\_validator to Envelope that accepts protocol or protocol\_version, timestamp or ts\_utc. Log deprecation warning when V1 keys are used. |
| Port V1 test\_flow.sh to pytest | **Medium** | Backend | Convert all 10 test steps to httpx-based async pytest functions. Add to CI. |

## **Phase 3 — Firmware Unification (Week 5–6)**

| Goal | V1 sketch users can migrate to V2 PlatformIO structure with a documented migration guide. NTP timestamp, HMAC sig, and config\_update support added to firmware. |
| :---- | :---- |

| Task | Priority | Owner | Description |
| :---- | ----- | :---- | :---- |
| Add NTP timestamp to Protocol.cpp | **High** | Firmware | Integrate arduino-libraries/NTPClient in Application::begin(); populate nowUtc() from NTP instead of uptime stub. Fall back to uptime if NTP unavailable. |
| Implement HMAC-SHA256 sig field | **Medium** | Firmware | Add optional HMAC-SHA256 of payload using per-node secret stored in NVS. Gate on settings.enableSig flag. Gateway verifies if sig present. |
| Write V1→V2 firmware migration guide | **High** | Docs | Step-by-step guide: install PlatformIO, create BaseModule subclass, move \#defines to config.node.json, flash and verify registration. |
| Add config\_update handler to Application | **Medium** | Firmware | Subscribe to cnp/v1/nodes/{id}/config topic. On receipt, validate config\_version \> current, update NVS, apply intervals without reboot. |

## **Phase 4 — Production Hardening (Week 7–8)**

| Goal | TLS MQTT, per-node secrets, PostgreSQL migration path, CI/CD pipeline, and full test coverage. System is field-deployable. |
| :---- | :---- |

| Task | Priority | Owner | Description |
| :---- | ----- | :---- | :---- |
| MQTT TLS configuration | **Critical** | Ops | Document Mosquitto TLS setup; add WiFiClientSecure option to TransportMqtt; add MQTT\_TLS\_ENABLED env var to gateway settings. |
| Per-node secret provisioning | **Critical** | Security | Generate unique secret per node\_id on first registration. Store HMAC hash in nodes.node\_secret\_hash. Provision secret into NVS via QR/USB at setup time. |
| PostgreSQL adapter | **Medium** | Backend | Thin adapter layer replacing aiosqlite calls with asyncpg; same SQL surface. Activated by GATEWAY\_DB\_URL env var starting with postgresql://. |
| CI/CD pipeline | **High** | DevOps | GitHub Actions workflow: lint (ruff, mypy), pytest with coverage gate (80%), firmware build check (pio ci), schema validation script. |

# **Unified System Architecture Specification**

## **System Topology**

The US+ canonical topology is:

* ESP32-C3 Node → WiFi → MQTT Broker (Mosquitto) → GatewayMqttBridge → FastAPI Gateway → SQLite/PostgreSQL

* ESP32-C3 Node ← WiFi ← MQTT Broker ← GatewayMqttBridge (commands, acks, config\_updates)

* Legacy V1 HTTP Node → WiFi → HTTP Compat Adapter → FastAPI Gateway (translation layer, deprecated)

* Codessa Core / Dashboard → REST API (/api/\*) → FastAPI Gateway → SQLite/PostgreSQL

* Codessa Memory Cortex ← Memory Bridge Hook ← FastAPI Gateway (event forwarding, pluggable)

## **Updated Data Models**

### **nodes Table (US+)**

| Column | Type | Required | Notes |
| :---- | :---- | :---- | :---- |
| node\_id | TEXT PK | Yes | Pattern: ^\[a-z0-9-\]{3,64}$ |
| device\_uid | TEXT | Yes | Immutable silicon or install-time UID (from V2) |
| node\_name | TEXT | Yes | Human-readable label |
| node\_type | TEXT | Yes | sensor | actuator | hybrid | gateway |
| protocol\_version | TEXT | Yes | Default: CNPv1 |
| firmware\_version | TEXT | Yes | Semver recommended |
| hardware\_model | TEXT | Yes | e.g. esp32-c3-supermini (from V2) |
| capabilities\_json | TEXT | Yes | JSON capability object |
| config\_version | INTEGER | Yes | Config epoch, increments on config\_update (from V2) |
| status | TEXT | Yes | 7-state: unknown/registering/online/degraded/offline/blocked/retired |
| last\_seen\_utc | TEXT | No | ISO-8601 UTC |
| first\_seen\_utc | TEXT | Yes | Immutable registration timestamp |
| boot\_reason | TEXT | No | power\_on | reset | watchdog | ota | deep\_sleep | unknown |
| heartbeat\_interval\_sec | INTEGER | Yes | Default: 60 |
| offline\_after\_sec | INTEGER | Yes | Default: 180 |
| last\_rssi | INTEGER | No | dBm |
| battery\_pct | REAL | No | 0–100, NULL for wired |
| free\_heap\_bytes | INTEGER | No | From heartbeat (from V2) |
| queue\_depth | INTEGER | Yes | EventQueue size at last heartbeat (from V2) |
| supports\_ota | INTEGER | Yes | 0 or 1 (from V2) |
| ota\_channel | TEXT | No | stable | beta (from V2) |
| ota\_last\_result | TEXT | No | Last OTA outcome (from V2) |
| node\_secret\_hash | TEXT | No | HMAC key hash for message verification (US+ new) |
| zone | TEXT | No | Moved from top-level to metadata\_json; kept for view compat |
| tags\_json | TEXT | Yes | Default: \[\] (from V2) |
| metadata\_json | TEXT | Yes | Default: {} — zone, site, owner, notes (from V2) |

### **events Table (US+)**

The V2 events table is adopted without modification, plus the addition of received\_at from V1 for gateway-side deduplication windows.

## **US+ API Specification**

| Method | Path | Auth | Description |
| :---- | :---- | :---- | :---- |
| GET | /api/health | None | Liveness probe. Returns {status, version, db\_ok, broker\_ok}. |
| GET | /api/nodes | Bearer | List all nodes. Optional: ?status=online\&zone=office\&limit=100 |
| GET | /api/nodes/{node\_id} | Bearer | Single node detail with latest heartbeat and capability data. |
| PATCH | /api/nodes/{node\_id}/config | Bearer | Update node config. Publishes config\_update via MQTT. |
| DELETE | /api/nodes/{node\_id} | Bearer | Retire node (sets status=retired). Does not delete historical data. |
| GET | /api/events | Bearer | Recent events. Optional: ?category=alert\&priority=high\&limit=50 |
| GET | /api/alerts | Bearer | Shorthand for events?priority=high,critical within last 24h. |
| GET | /api/errors | Bearer | Recent errors. Optional: ?severity=error,critical\&node\_id=x |
| POST | /api/nodes/{node\_id}/commands | Bearer | Issue command. Body: CommandRequest. Returns {command\_id, status}. |
| GET | /api/nodes/{node\_id}/commands/{cmd\_id} | Bearer | Get command status and result. |
| GET | /api/summary | Bearer | Aggregated view: total nodes, online count, alerts last 24h, errors. |
| POST | /v1/compat/node/hello | Token | \[V1 compat\] Accepts V1 envelope format, translates to V2 and upserts. |
| POST | /v1/compat/node/heartbeat | Token | \[V1 compat\] Accepts V1 heartbeat, updates node status. |
| POST | /v1/compat/node/event | Token | \[V1 compat\] Accepts V1 event envelope, enriches missing fields. |
| POST | /v1/compat/node/error | Token | \[V1 compat\] Accepts V1 error format, maps to V2 severity model. |
| GET | /v1/compat/node/commands/{node\_id} | Token | \[V1 compat\] Returns pending command in V1 format for polling nodes. |

## **Backward Compatibility Preservation**

The following table specifies exactly how V1 field names map to V2 equivalents in the HTTP compatibility adapter:

| V1 Field | V2 Field | Transformation | Deprecation |
| :---- | :---- | :---- | :---- |
| protocol | protocol\_version | Direct rename; assert value \== "CNPv1" | Warn in logs |
| timestamp | ts\_utc | Rename; normalize to Z suffix | Warn in logs |
| (absent) | message\_id | Generate ULID on receipt at gateway | No warning needed |
| (absent) | qos | Default to 0 (no guarantee) | No warning needed |
| payload.params | payload.arguments | Key rename in command payloads | Warn in logs |
| payload.error\_code | payload.code | Rename; set domain="LEGACY", severity="error" | Warn in logs |
| payload.event\_id | message\_id | Promote to envelope field; remove from payload | Warn in logs |

# **Testing Requirements**

## **Test Coverage Targets**

| Component | Current Coverage | US+ Target | Key Test Areas |
| :---- | :---- | :---- | :---- |
| Gateway REST API | V1: 0%  /  V2: \~10% | 85% | All endpoints, auth, 4xx/5xx, edge cases |
| MQTT Bridge handlers | V2: 0% | 80% | hello, heartbeat, event, error, ack, command\_result |
| Registry functions | V2: 0% | 80% | upsert\_node, update\_heartbeat, mark\_offline\_nodes |
| Storage functions | V2: 0% | 80% | insert\_event, insert\_error, create\_command, upsert\_result |
| Pydantic models | V2: 0% | 90% | Valid and invalid envelopes, field validators |
| V1 compat adapter | V1: 0% | 85% | All 5 V1 endpoints, field translation, error handling |
| Firmware (simulation) | Both: 0% | 60% | Protocol JSON generation, queue overflow, command parsing |

## **Test Suite Structure**

* gateway/tests/test\_health.py — liveness, DB connectivity, broker connectivity

* gateway/tests/test\_nodes.py — CRUD operations, status transitions, 404 handling

* gateway/tests/test\_events.py — ingestion, deduplication, priority filtering

* gateway/tests/test\_commands.py — issue, poll, ack, timeout, dry\_run

* gateway/tests/test\_mqtt\_bridge.py — handler dispatch, registration ack, command publish

* gateway/tests/test\_compat.py — V1 field translation, missing field defaults, error mapping

* gateway/tests/test\_validation.py — Pydantic Envelope rejection of malformed inputs

* firmware/tests/test\_protocol.py — Desktop-side C++ unit tests via platformio test target

| NOTE | All tests must pass with PYTHONPATH=gateway pytest gateway/tests \-q \--cov=app \--cov-report=term-missing. Coverage below 80% must block merge. |
| :---- | :---- |

## **Integration Test Flow (Replaces test\_flow.sh)**

The following test sequence shall be implemented as a single pytest file (test\_integration.py) using httpx.AsyncClient and a real in-memory SQLite DB:

1. Health endpoint returns 200 with db\_ok=true and broker\_ok=false (no broker in CI).

2. POST /v1/compat/node/hello with V1 envelope → 200, node appears in /api/nodes.

3. POST /v1/compat/node/heartbeat → 200, node status=online, last\_seen updated.

4. POST /v1/compat/node/event (telemetry) → 200, event in /api/events.

5. POST /v1/compat/node/event (priority=high) → 200, event in /api/alerts.

6. POST /v1/compat/node/error → 200, error stored with severity=error, domain=LEGACY.

7. POST /api/nodes/{node\_id}/commands → 200, command\_id returned.

8. GET /v1/compat/node/commands/{node\_id} → command in V1 format (params not arguments).

9. POST /v1/compat/node/command\_result → 200, command status=executed.

10. GET /api/summary → total\_nodes=1, online=1, alerts\_24h=1.

11. Simulate offline: advance last\_seen by \>180s, trigger offline\_watcher → status=offline.

# **Deployment Procedures**

## **Environment Prerequisites**

| Component | Minimum Version | Purpose |
| :---- | :---- | :---- |
| Python | 3.11+ | Gateway runtime |
| Mosquitto (or compatible MQTT broker) | 2.0+ | Message broker for MQTT transport |
| PlatformIO Core | 6.1+ | Firmware build and upload toolchain |
| Node.js | 18+ (for docx/tools) | Development tooling only |
| SQLite | 3.35+ (WAL mode) | Default persistence; PostgreSQL 14+ for scale |

## **Gateway Deployment**

12. Clone repository and create virtual environment: python \-m venv .venv && source .venv/bin/activate

13. Install dependencies: pip install \-r gateway/requirements.txt

14. Configure environment variables (see table below).

15. Initialize database: python \-c "import asyncio; from app.core.db import init\_db; asyncio.run(init\_db('./cnp.db'))"

16. Start gateway: uvicorn app.main:app \--host 0.0.0.0 \--port 8080 \--workers 1

17. Verify: curl http://localhost:8080/api/health → {status: ok}

| Environment Variable | Default | Required | Description |
| :---- | :---- | :---- | :---- |
| MQTT\_BROKER\_HOST | 127.0.0.1 | Yes | IP or hostname of MQTT broker |
| MQTT\_BROKER\_PORT | 1883 | No | MQTT port (8883 for TLS) |
| MQTT\_USERNAME | (empty) | No | MQTT auth username |
| MQTT\_PASSWORD | (empty) | No | MQTT auth password |
| GATEWAY\_DB\_PATH | ./cnp\_gateway.db | No | SQLite path or postgresql:// URL for PostgreSQL |
| CNP\_OFFLINE\_AFTER\_SECONDS | 180 | No | Seconds before a silent node is marked offline |
| CNP\_GATEWAY\_ID | codessa-gateway-local | No | Gateway identity in register\_ack messages |
| CNP\_AUTH\_ENABLED | true | No | Enable X-CNP-Node-Token header validation |

## **Firmware Deployment**

18. Install PlatformIO: pip install platformio

19. Copy examples/config.node.example.json to firmware/config/config.node.json and edit fields.

20. Connect ESP32-C3 via USB-C data cable.

21. Build and upload: cd firmware && pio run \-t upload

22. Monitor: pio device monitor \--baud 115200

23. Verify node appears in gateway within 30 seconds: curl http://GATEWAY:8080/api/nodes

| RECOVERY | If upload fails: hold BOOT, tap RESET, release RESET, release BOOT, then retry pio run \-t upload. See ESP32-C3 boot mode documentation. |
| :---- | :---- |

# **Success Metrics for Unified System Validation**

## **Functional Correctness**

| Metric | Target | Measurement Method |
| :---- | :---- | :---- |
| Node registration success rate | ≥ 99.9% | Count successful register\_ack / total hello attempts over 7-day soak |
| Command delivery latency (MQTT) | \< 200 ms p95 | Timestamp delta: command issued → ack received; benchmark\_gateway.py |
| Event deduplication rate | 0 duplicate message\_ids in events table | SELECT count(\*) vs count(DISTINCT message\_id) on events |
| V1 compat adapter translation accuracy | 100% | Parametrised pytest with 50 V1 message fixtures; assert V2 schema validity |
| Offline detection accuracy | \< 30s lag after heartbeat timeout | Integration test: advance clock, trigger watcher, assert status=offline |
| OTA success rate (simulation) | ≥ 95% | OtaManager unit test with mock HTTPS server and known firmware binary |

## **Performance**

| Metric | Target | Measurement Method |
| :---- | :---- | :---- |
| Gateway throughput (events/sec) | ≥ 500 events/sec on single core | benchmark\_gateway.py extended with aiosqlite write benchmark |
| JSON serialization (per message) | \< 50 µs mean, \< 150 µs p95 | benchmark\_gateway.py baseline (current mean \~15 µs) |
| SQLite write latency (WAL mode) | \< 2 ms p99 for single INSERT | asyncio benchmark with 10k sequential inserts |
| MQTT broker round-trip latency | \< 10 ms on LAN | Node → publish → bridge receive → ack timestamp comparison |
| Memory footprint (firmware) | \< 100 KB heap used at idle | Free heap reported in heartbeat; assert queue\_depth=0 at idle |

## **Reliability and Maintainability**

| Metric | Target | Measurement Method |
| :---- | :---- | :---- |
| Test coverage (gateway) | ≥ 80% | pytest \--cov; fail CI if below threshold |
| Test coverage (firmware simulation) | ≥ 60% | pio test; report coverage on desktop target |
| Linting / type check | 0 ruff errors, 0 mypy errors | CI: ruff check gateway/ && mypy gateway/ |
| Cold start time (gateway) | \< 3 seconds to ready | Time from process start to /api/health 200 |
| Node reconnect recovery | \< 60 seconds to re-online | Kill node WiFi; restore; measure time to status=online in registry |
| DB migration correctness | 0 data loss on V1→V2 schema migration | Run migration on seeded V1 test DB; assert row counts and spot-check values |
| Documentation completeness | All public API endpoints documented | OpenAPI spec auto-generated by FastAPI; verify no undocumented routes |

# **Appendix A — Merge Conflict Resolution Strategies**

The following naming conflicts must be resolved before any shared code can compile or be tested jointly:

| Conflict ID | Location | V1 Value | V2 Value | Resolution |
| :---- | :---- | :---- | :---- | :---- |
| MC-01 | Envelope field | protocol | protocol\_version | Adopt protocol\_version. V1 compat adapter handles rename. |
| MC-02 | Envelope field | timestamp | ts\_utc | Adopt ts\_utc. Pydantic alias accepts both. |
| MC-03 | Command payload | params | arguments | Adopt arguments. Compat adapter renames on inbound. |
| MC-04 | Error payload | error\_code / error\_msg | severity / domain / code / message | Adopt V2 model. Map V1 error\_code to code; set domain=LEGACY. |
| MC-05 | DB column | battery (int) | battery\_pct (REAL) | Adopt battery\_pct REAL. Migration: cast existing int values. |
| MC-06 | Gateway port | Port 5000 | Port 8080 | Adopt 8080\. V1 test\_flow.sh updated. |
| MC-07 | hello field | capabilities.power\_mode | capabilities.power.source | Adopt V2 nested power object. Compat adapter restructures on inbound. |
| MC-08 | Heartbeat | battery: \-1 (sentinel) | battery\_pct: null | Adopt null. Compat adapter converts \-1 to null. |

# **Appendix B — Technical Debt Register**

| TD-ID | System | Description | Effort | Priority |
| :---- | :---- | :---- | :---- | ----- |
| TD-01 | V2 | No FK constraints enforced in db.py SCHEMA\_SQL despite being in docs | 1h | **Medium** |
| TD-02 | V2 | mqtt\_client.py subscribes to cnp/v1/nodes/+/+ — misses cmd/out and config topics (two-level wildcard issue) | 2h | **High** |
| TD-03 | V2 | gateway/tests/test\_api.py uses synchronous TestClient with lifespan — MQTT bridge is never started in tests | 4h | **High** |
| TD-04 | V2 | routes.py /nodes and /nodes/{id} return all columns including node\_secret\_hash — must be excluded from API responses | 1h | **Critical** |
| TD-05 | V2 | Protocol.cpp::nowUtc() is a stub returning empty string — timestamp field will be empty until NTP integrated | 3h | **High** |
| TD-06 | V1 | gateway.py uses millis()%5000 polling heuristic — will miss polls if loop() is slow | 1h | **Medium** |
| TD-07 | Both | No rate limiting on any endpoint — a misbehaving node can flood the gateway with events | 4h | **Medium** |
| TD-08 | Both | Node ID validation regex differs: V1 uses cnp-{zone}-{fn}-{idx} pattern; V2 uses ^\[a-z0-9-\]{3,64}$ — V2 is looser and should be adopted | 30m | **Low** |

# **Appendix C — Dependency Matrix**

| Package | V1 | V2 | US+ Decision |
| :---- | :---- | :---- | :---- |
| fastapi | ≥0.100 (implied) | 0.116.1 | Pin to 0.116.x |
| uvicorn\[standard\] | Yes | 0.35.0 | Pin to 0.35.x |
| pydantic | Not used | 2.11.7 | Pin to 2.x; required for Envelope validation |
| aiosqlite | Not used | 0.21.0 | Adopt; replace sync sqlite3 |
| asyncio-mqtt | Not used | 0.16.2 | Adopt for MQTT bridge |
| orjson | Not used | 3.11.1 | Adopt for high-throughput JSON serialization |
| httpx | Not used | 0.28.1 | Adopt for integration tests |
| pytest \+ pytest-asyncio | Not used | 8.4.1 / 1.1.0 | Adopt; add pytest-cov |
| ArduinoJson (firmware) | 6.x | 7.0.4+ | Adopt 7.x (breaking API change, see migration) |
| PubSubClient (firmware) | Not used | 2.8 | Adopt for MQTT transport |

CNP-SPEC-001 v1.0  ·  Codessa Systems  ·  March 2026  ·  CONFIDENTIAL