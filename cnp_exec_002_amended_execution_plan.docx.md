

CODESSA NODE PROTOCOL v1

**Amended US+ Execution Plan**

| Supersedes | CNP-SPEC-001 v1.0 — Unified System Technical Specification |
| :---- | :---- |
| Document No. | CNP-EXEC-002 |
| Version | 1.0 — Amended |
| Status | Active — Implementation Program |
| Date | March 2026 |
| Classification | Internal — Engineering |
| Primary change | Security-first phase ordering, DoS protection, CI gate repair, secrets redaction |

# **Why This Amendment Exists**

CNP-SPEC-001 was correct in its analysis but wrong in its ordering. It treated security, CI integrity, and survivability as concerns that could follow feature work. That posture was flawed. This document replaces that ordering with a single governing principle:

| Protect correctness and survivability first. Then add compatibility. Then add scale. This means: prevent silent failure → prevent data corruption → prevent gateway collapse → preserve backward compatibility → improve operator experience → scale out. |
| :---- |

Four specific deficiencies in the original plan triggered this amendment:

* **No rate limiting.** TD-07 was classified Medium and deferred to Phase 4\. A single misbehaving node can flood the gateway and starve the entire fleet. This is a Phase 1 survivability requirement, not a later optimisation.

* **Security scaffolding deferred.** Per-node secrets and TLS were placed in Phase 4 (Weeks 7–8). Any node deployed before that point operates on an unprotected trust model. Security structure must exist before any production node connects.

* **CI test harness broken.** TD-03 documents that the MQTT bridge cannot start under the existing TestClient fixture. All MQTT transport coverage targets are therefore fiction until this is repaired. No new transport feature work should begin until the harness is fixed.

* **Secrets exposed via API.** TD-04 (Critical) identified that /api/nodes returns all columns. Once node\_secret\_hash is added, it will be served to any authenticated caller listing nodes. This is a same-day patch item with no acceptable delay.

# **Governing Architecture Principles**

The following principles are locked for US+. They are not subject to phase trade-offs.

| Principle | Rule | Source |
| :---- | :---- | ----- |
| Canonical envelope |  | **V2 ADOPT** |
| Canonical firmware | V2 modular OOP architecture (Application \+ BaseModule). V1 monolith is ported as ExampleModule only. | **V2 ADOPT** |
| Transport | MQTT-first for runtime. HTTP permitted for provisioning, diagnostics, and V1 compat only. | **V2 ADOPT** |
| Validation | All inbound messages validated by Pydantic Envelope before any DB write or dispatch. | **V2 ADOPT** |
| DTOs | Explicit response DTOs everywhere. SELECT \* is prohibited in API-facing queries. | **NEW** |
| SQL views | V1 views (v\_node\_status, v\_recent\_alerts, v\_pending\_commands, v\_event\_summary) ported to V2 schema. | **V1 ABSORB** |
| Auth | X-CNP-Node-Token per-node header gate on all inbound node endpoints. Baseline present from day one. | **V1 ABSORB** |
| Rate limiting | Rolling-window per-node, per-IP, and global limits on HTTP and MQTT ingestion paths. | **NEW** |
| Secret hygiene | node\_secret\_hash never leaves the DB layer. Auth material excluded from all list/detail endpoints. | **NEW** |
| Test gate | MQTT bridge testable in isolation. 80% coverage on gateway enforced by CI. No merge without green. | **AMENDED** |
| Heartbeat trim | AFTER INSERT trigger caps heartbeats at 1000 rows per node. No application-layer management needed. | **V1 ABSORB** |

# **Amended Phase Structure**

The original four phases are retained but their content has been significantly reordered. The table below shows every task, its origin disposition, and its amended placement.

| Task | Original | Amended | Reason |
| :---- | ----- | ----- | :---- |
| HTTP \+ MQTT rate limiting | **PHASE 4** | **PHASE 1** | Gateway survivability — must precede any fleet onboarding |
| Redact node\_secret\_hash from API | **PHASE 4** | **PHASE 1** | Same-day Critical patch — TD-04 |
| Repair MQTT bridge test harness | **PHASE 2** | **PHASE 1** | All transport coverage is fiction without this — TD-03 |
| Fix MQTT wildcard subscription bug | **PHASE 1** | **PHASE 1** | Retained — TD-02 Critical |
| Add Pydantic Envelope validation | **PHASE 1** | **PHASE 1** | Retained |
| Port V1 SQL views | **PHASE 1** | **PHASE 1** | Retained |
| Auth token middleware (X-CNP-Node-Token) | **PHASE 2** | **PHASE 1** | Security scaffolding must exist before nodes connect |
| Explicit response DTOs (no SELECT \*) | **PHASE 4** | **PHASE 1** | Enables safe addition of secret column later |
| Add heartbeat trim trigger | **PHASE 1** | **PHASE 1** | Retained |
| TLS broker documentation | **PHASE 4** | **PHASE 2** | Front-loaded — must cover pilot nodes |
| Per-node secret column \+ provisioning spec | **PHASE 4** | **PHASE 2** | Front-loaded — scaffolding before V1 compat |
| V1 HTTP compat adapter | **PHASE 2** | **PHASE 2** | Retained |
| V1 → V2 envelope translation | **PHASE 2** | **PHASE 2** | Retained |
| V1 → V2 DB migration DDL | **PHASE 2** | **PHASE 2** | Retained |
| Port V1 test\_flow.sh to pytest | **PHASE 2** | **PHASE 2** | Retained |
| NTP-backed timestamps | **PHASE 3** | **PHASE 3** | Retained |
| HMAC-SHA256 sig field | **PHASE 3** | **PHASE 3** | Retained — requires per-node secrets from Phase 2 |
| config\_update MQTT handler | **PHASE 3** | **PHASE 3** | Retained |
| message\_id deduplication guarantees | **PHASE 3** | **PHASE 3** | Retained |
| Command timeout reconciliation | **PHASE 3** | **PHASE 3** | Retained |
| EventQueue retry semantics | **PHASE 3** | **PHASE 3** | Retained |
| PostgreSQL adapter | **PHASE 4** | **PHASE 4** | Retained |
| CI/CD pipeline quality gates | **PHASE 4** | **PHASE 4** | Retained |
| Load and soak testing | **PHASE 4** | **PHASE 4** | Retained |
| Migration tooling | **PHASE 4** | **PHASE 4** | Retained |
| Dashboard integration | **PHASE 4** | **PHASE 4** | Retained |

| PHASE 1 | Stabilise the Core | Weeks 1–2 |
| :---: | :---- | ----: |

Phase 1 now has a single mandate: make the system correct, safe, and testable before any new feature work proceeds. No V1 compatibility work, no migration scripts, no scale work. Just a stable foundation.

### **Phase 1 Tasks**

| ID | Task | Priority | Effort | Notes |
| :---- | :---- | ----- | :---- | :---- |
| P1-01 |  | **CRITICAL** | 2h | TD-02. Without this, command results and errors are silently dropped |
| P1-02 |  | **CRITICAL** | 2h | TD-04 same-day patch. Implement before adding secret column |
| P1-03 |  | **CRITICAL** | 1 day | TD-03 hard gate. Blocks all transport coverage work |
| P1-04 |  | **CRITICAL** | 4h | TD-07 elevated to Phase 1\. Prevents fleet flood attacks |
| P1-05 |  | **CRITICAL** | 4h | MQTT-side counterpart to P1-04. Backpressure must log rate-limit events |
| P1-06 | Add Pydantic Envelope validation — reject all inbound messages failing schema before any DB write or dispatch. Return structured 422 with field-level error detail | **HIGH** | 4h | G-09. Prevents silent data corruption |
| P1-07 | Auth token middleware — X-CNP-Node-Token header gate on all node-inbound routes. Validate against nodes table. 401 on missing/invalid token | **HIGH** | 3h | Front-loaded from Phase 2\. Security scaffold must exist before V1 nodes connect |
| P1-08 |  | **HIGH** | 2h | G-15. Powers dashboard without app-layer aggregation |
| P1-09 | Heartbeat trim trigger — AFTER INSERT on heartbeats table, delete oldest rows beyond 1000 per node\_id | **MEDIUM** | 1h | V1 self-managing retention. No application-layer management needed |
| P1-10 | Expand pytest coverage — nodes, events, commands, MQTT handlers, validation rejection. Target: 60% gateway coverage | **HIGH** | 1 day | Pre-condition for Phase 2 transport work |

### **Phase 1 Rate Limiting Specification**

Rate limits must be observable and auditable. Every breach must emit a structured log event and be queryable from the gateway.

| Surface | Limit | Window | Breach action | Observable |
| :---- | :---- | :---- | :---- | :---- |
| HTTP per node\_id | 60 requests | 60s rolling | 429 \+ Retry-After header \+ log event | `rate_limit.http.node_breach` |
| HTTP per source IP | 200 requests | 60s rolling | 429 \+ Retry-After header \+ log event | `rate_limit.http.ip_breach` |
| HTTP global | 2000 requests | 60s rolling | 429 \+ Retry-After header \+ alert | `rate_limit.http.global_breach` |
| MQTT per client-ID | 10 msg/sec | 1s sliding | Drop message \+ log event | `rate_limit.mqtt.client_breach` |
| MQTT burst allowance | 50 msg/sec | 5s window | Drop excess \+ quarantine after 3 breaches | `rate_limit.mqtt.burst_breach` |
| MQTT invalid message | 3 per 60s | 60s rolling | Disconnect \+ quarantine client-ID for 5 min | `rate_limit.mqtt.invalid_breach` |

### **Phase 1 Exit Gate**

| GATE | Gate P1.1: MQTT broker not required. Gateway starts, bridge test harness initialises, and all handler unit tests pass in CI. |
| :---: | :---- |

| GATE | Gate P1.2: Rate limit tests pass: a client sending 100 req/min is throttled to 60\. A second client is unaffected. Breach events appear in gateway logs. |
| :---: | :---- |

| GATE | Gate P1.3: GET /api/nodes response contains zero auth or secret fields. Verified by automated assertion in test\_nodes.py. |
| :---: | :---- |

| GATE | Gate P1.4: Malformed envelope (missing message\_id, invalid node\_id pattern, wrong protocol\_version) returns 422 with field-level error. No DB write occurs. |
| :---: | :---- |

| GATE | Gate P1.5: Gateway pytest suite reaches 60% coverage. Coverage report published as CI artifact. No merge to main without green. |
| :---: | :---- |

| PHASE 2 | Secure Compatibility Layer | Weeks 3–4 |
| :---: | :---- | ----: |

Phase 2 delivers the V1-to-V2 bridge while establishing the security structure that all future nodes will depend on. Legacy nodes can connect safely without requiring immediate reflash. No legacy node should be able to connect on a weaker trust model than V2 nodes.

### **Phase 2 Tasks**

| ID | Task | Priority | Effort | Notes |
| :---- | :---- | ----- | :---- | :---- |
| P2-01 | TLS broker documentation — Mosquitto TLS certificate setup, add WiFiClientSecure path to TransportMqtt, MQTT\_TLS\_ENABLED gateway env var, test with self-signed cert | **CRITICAL** | 1 day | Front-loaded from Phase 4\. Must cover pilot nodes before any field deployment |
| P2-02 |  | **CRITICAL** | 1 day | Front-loaded from Phase 4\. Enables HMAC in Phase 3 |
| P2-03 | V1 HTTP compat adapter — new FastAPI router at /v1/compat/\* accepting V1 envelope format. Translates protocol→protocol\_version, timestamp→ts\_utc, params→arguments, error\_code→code+domain. Generates message\_id (ULID) and qos=0 defaults | **HIGH** | 1 day | G-01 / G-04 resolution. Allows V1 fleet to operate without reflash |
| P2-04 | V1 → V2 DB migration DDL — ALTER TABLE scripts for 9 new columns, status enum expansion, battery int→REAL cast. Includes rollback script. Validated against V1 test fixture | **HIGH** | 4h | G-13 / G-14. Must produce zero data loss on seeded V1 DB |
| P2-05 |  | **HIGH** | 2h | G-04 / MC-01 / MC-02 resolution |
| P2-06 | Port test\_flow.sh to pytest — 11-step integration test using httpx.AsyncClient with real in-memory SQLite. Covers full V1 compat lifecycle. Added to CI. | **HIGH** | 4h | G-23. Replaces manual curl script with deterministic CI test |
| P2-07 | Auth enforcement on compat endpoints — compat adapter uses same X-CNP-Node-Token middleware as V2 routes. V1 nodes must provision a token before connecting | **HIGH** | 2h | Security consistency. No weaker auth for legacy nodes |
| P2-08 | API summary endpoint — GET /api/summary returns total\_nodes, online\_count, alerts\_24h, errors\_24h, pending\_commands. Backed by V1 SQL views | **MEDIUM** | 2h | Dashboard usability. Absorbs V1 operational surface |

### **Phase 2 Field Translation Map**

| V1 Field | V2 Field | Transformation | Log warning |
| :---- | :---- | :---- | :---- |
| `protocol` | `protocol_version` | Rename. Assert value \== "CNPv1" | Yes — DEPRECATION\_V1\_KEY |
| `timestamp` | `ts_utc` | Rename. Normalise to Z suffix | Yes — DEPRECATION\_V1\_KEY |
| (absent) | `message_id` | Generate ULID at gateway boundary | No |
| (absent) | `qos` | Default to 0 | No |
| `payload.params` | `payload.arguments` | Key rename in command payloads | Yes — DEPRECATION\_V1\_KEY |
| `payload.event_id` | `message_id` | Promote to envelope. Remove from payload | Yes — DEPRECATION\_V1\_KEY |
| `payload.error_code` | `payload.code` | Rename. Set domain=LEGACY, severity=error | Yes — DEPRECATION\_V1\_KEY |
| `battery: -1` | `battery_pct: null` | Convert sentinel \-1 to null | No |
| `capabilities.power_mode` | `capabilities.power.source` | Restructure to nested power object | Yes — DEPRECATION\_V1\_KEY |

### **Phase 2 Exit Gate**

| GATE | Gate P2.1: V1 migration DDL runs against seeded V1 test DB with zero data loss. Row counts match pre-migration. Spot-check values verified by automated assertion. |
| :---: | :---- |

| GATE | Gate P2.2: V1 compat integration test (11 steps) passes in CI against /v1/compat/\* endpoints. All field translations verified by schema assertion. |
| :---: | :---- |

| GATE | Gate P2.3: TLS broker test passes with self-signed certificate. Gateway connects with MQTT\_TLS\_ENABLED=true. Connection refused without cert. |
| :---: | :---- |

| GATE | Gate P2.4: Coverage reaches 75%. compat adapter and migration paths covered. No merge without green. |
| :---: | :---- |

| PHASE 3 | Operational Hardening | Weeks 5–6 |
| :---: | :---- | ----: |

Phase 3 makes message correctness and fleet behaviour deterministic. After Phase 3, the system makes guarantees it could not make before: messages are deduplicated, commands time out reliably, timestamps are real, and firmware config is updatable without reflash.

### **Phase 3 Tasks**

| ID | Task | Priority | Effort | Notes |
| :---- | :---- | ----- | :---- | :---- |
| P3-01 | NTP-backed timestamps — integrate NTPClient in Application::begin(). Populate Protocol::nowUtc() from NTP. Fall back to uptime stub if NTP unavailable within 5s. Log fallback. | **HIGH** | 3h | TD-05. Fixes empty ts\_utc fields in firmware |
| P3-02 | HMAC-SHA256 sig field — optional per-node message signing using secret from NVS. Gate on settings.enableSig. Gateway verifies sig when present. Rejects tampered messages. | **MEDIUM** | 1 day | G-21 partial. Requires per-node secrets from P2-02 |
| P3-03 |  | **HIGH** | 4h | G-24 resolution. Eliminates reflash-for-config |
| P3-04 |  | **HIGH** | 3h | G-02 resolution. Prevents double-counting on reconnect |
| P3-05 | Command timeout reconciliation — background task scans commands WHERE status=queued AND issued\_ts \< now()-timeout\_ms. Mark as timeout. Emit timeout event to node\_id/events topic. | **HIGH** | 3h | Prevents permanently-pending commands accumulating |
| P3-06 | EventQueue retry semantics — firmware-side: retry queued messages up to 3 times with exponential backoff. Mark as dead\_letter after max retries. Report dead\_letter count in heartbeat queue\_depth. | **MEDIUM** | 4h | G-07 completion. Firmware-layer correctness |
| P3-07 | Offline timeout hardening — offline\_watcher checks last\_seen\_utc against per-node offline\_after\_sec (not global). Emits fleet\_event on transition online→offline. Searchable by zone. | **MEDIUM** | 2h | Per-node granularity. Improves degraded→offline detection |

### **Phase 3 Exit Gate**

| GATE | Gate P3.1: Duplicate event (same message\_id sent twice) produces exactly one row in events table. Verified by integration test. |
| :---: | :---- |

| GATE | Gate P3.2: Command issued with timeout\_ms=5000 transitions to status=timeout within 10 seconds of issue if no ack received. Verified by integration test. |
| :---: | :---- |

| GATE | Gate P3.3: config\_update message with heartbeat\_interval\_sec=10 applied by firmware without reboot. Next heartbeat arrives within 15 seconds. Verified in firmware simulation test. |
| :---: | :---- |

| GATE | Gate P3.4: Coverage reaches 80%. All Phase 3 paths covered. CI blocks merge below threshold. |
| :---: | :---- |

| PHASE 4 | Scale and Maintainability | Weeks 7–8 |
| :---: | :---- | ----: |

Phase 4 prepares the system for larger fleet rollout and sustained operations. The core is now correct, secure, and testable. Phase 4 adds horizontal scale paths, automated quality gates, and the operational tools needed for production support.

### **Phase 4 Tasks**

| ID | Task | Priority | Effort | Notes |
| :---- | :---- | ----- | :---- | :---- |
| P4-01 |  | **MEDIUM** | 1 day | Scale path. Same SQL surface, different driver |
| P4-02 | CI/CD pipeline — GitHub Actions: ruff \+ mypy lint gate, pytest coverage gate (80%), firmware pio build check, schema validation script, migration DDL dry-run on PR | **HIGH** | 1 day | Quality gate. Blocks merge on any failure |
| P4-03 | Load and soak testing — extend benchmark\_gateway.py: 500 events/sec sustained throughput test, 10k node simulation, 1-hour soak at 100 nodes. Report p50/p95/p99 latencies. | **HIGH** | 1 day | Validates ≥500 events/sec target from spec |
| P4-04 | Migration tooling — CLI script migrate.py for V1→V2 schema migration with dry-run mode, per-table progress reporting, rollback checkpoint, and post-migration integrity check | **HIGH** | 4h | Enables controlled fleet migration |
| P4-05 | Fleet diagnostics surface — /api/fleet/health endpoint aggregating queue\_depth, free\_heap\_bytes, wifi\_rssi trends, command lag, auth failure rate per node. Powers predictive monitoring. | **MEDIUM** | 4h | Blue-sky item pulled forward. Uses existing heartbeat data |
| P4-06 | Service boundary formalisation — define explicit interfaces between ingestion (MQTT bridge), command/control (routes), and query/API layers. Internal boundaries enable future microservice split without re-architecture. | **MEDIUM** | 4h | Architectural prep for CNP v2 event-driven split |

### **Phase 4 Exit Gate**

| GATE | Gate P4.1: benchmark\_gateway.py reports ≥500 events/sec sustained. p95 write latency \<2ms on SQLite WAL. p99 MQTT round-trip \<10ms on LAN. |
| :---: | :---- |

| GATE | Gate P4.2: CI pipeline blocks a PR with failing test, coverage below 80%, lint error, or migration DDL syntax error. Verified by deliberately failing each gate in a test PR. |
| :---: | :---- |

| GATE | Gate P4.3: migrate.py dry-run on 10k-row V1 fixture completes with zero errors. Live run produces identical row counts. Rollback restores original state. |
| :---: | :---- |

# **Updated Gap Register**

The following items amend the gap register from CNP-SPEC-001. Changes are flagged in the Disposition column. New items added by this amendment are marked NEW. Elevated items are marked ELEVATED.

| ID | Area | Description | Severity | Phase | Change |
| :---- | :---- | :---- | ----- | ----- | :---- |
| G-01 | Transport | HTTP polling creates 5s command latency and O(n) overhead | **HIGH** | **PHASE 1** | Retained — MQTT wildcard fix is now P1-01 |
| G-02 | Envelope | No message\_id — deduplication and tracing impossible | **CRITICAL** | **PHASE 1** | Retained. Pydantic rejects missing message\_id in P1-06 |
| G-03 | Transport | No rate limiting — single node can flood gateway | **CRITICAL** | **PHASE 1** | \[object Object\] from Medium/Phase 4 → Critical/Phase 1 |
| G-04 | Envelope | V1 key name divergence breaks shared parsers | **HIGH** | **PHASE 2** | Retained — Pydantic alias in P2-05 |
| G-05 | Firmware | V1 monolith prevents multi-node firmware reuse | **CRITICAL** | **PHASE 1** | Retained — V2 BaseModule is canonical |
| G-06 | Firmware | No persistent identity — node\_id lost on reflash | **HIGH** | **PHASE 1** | Retained — V2 IdentityManager is canonical |
| G-07 | Firmware | No event queue — messages lost on send failure | **HIGH** | **PHASE 3** | Retained — EventQueue retry in P3-06 |
| G-08 | Firmware | No OTA — firmware updates require physical access | **MEDIUM** | **PHASE 3** | Retained — OtaManager abstraction |
| G-09 | Gateway | No input validation — malformed messages corrupt DB silently | **CRITICAL** | **PHASE 1** | Retained — Pydantic validation in P1-06 |
| G-10 | Gateway | Sync sqlite3 blocks asyncio event loop | **HIGH** | **PHASE 1** | Retained — aiosqlite adopted |
| G-11 | Gateway | No MQTT bridge in V1 | **HIGH** | **PHASE 1** | Retained — V2 GatewayMqttBridge canonical |
| G-12 | Gateway | Auth token check absent from V2 REST API | **MEDIUM** | **PHASE 1** | \[object Object\] to Phase 1 — P1-07 |
| G-13 | Database | V1 nodes table missing 9 V2 columns | **HIGH** | **PHASE 2** | Retained — migration DDL in P2-04 |
| G-14 | Database | V1 missing acks table | **HIGH** | **PHASE 2** | Retained — V2 schema canonical |
| G-15 | Database | V2 missing V1 SQL helper views | **LOW** | **PHASE 1** | Retained — ported in P1-08 |
| G-16 | Database | V1 flat error model vs V2 severity+domain | **MEDIUM** | **PHASE 2** | Retained — compat adapter maps in P2-03 |
| G-17 | Events | V1 events lack requires\_ack, event\_seq, delivery\_mode | **HIGH** | **PHASE 2** | Retained — defaults applied in compat adapter |
| G-18 | Commands | V1 params vs V2 arguments naming divergence | **HIGH** | **PHASE 2** | Retained — translated in P2-03 |
| G-19 | Commands | V1 missing dry\_run, issued\_by fields | **MEDIUM** | **PHASE 2** | Retained — defaults applied in compat adapter |
| G-20 | Commands | V1 command polling latency unacceptable for actuators | **HIGH** | **PHASE 1** | Resolved by MQTT adoption |
| G-21 | Security | No per-node secrets or MQTT TLS | **CRITICAL** | **PHASE 2** | \[object Object\] from Phase 4 → Phase 2 — P2-01, P2-02 |
| G-22 | Testing | V1 zero automated tests | **HIGH** | **PHASE 1** | Retained — pytest suite in P1-10 |
| G-23 | Testing | test\_flow.sh not in CI | **MEDIUM** | **PHASE 2** | Retained — ported to pytest in P2-06 |
| G-24 | Config | V1 config in \#defines requires reflash | **HIGH** | **PHASE 3** | Retained — config\_update in P3-03 |
| G-25 | Heartbeat | V1 heartbeat missing seq, free\_heap, queue\_depth | **MEDIUM** | **PHASE 2** | Retained — compat adapter adds defaults |
| G-26 | Hello | V1 hello missing device\_uid, hardware\_model, boot\_reason, supports\_ota | **HIGH** | **PHASE 2** | Retained — compat adapter adds defaults |
| G-27 | Security | node\_secret\_hash exposed via SELECT \* in node list endpoint | **CRITICAL** | **PHASE 1** | \[object Object\] — TD-04 elevated. Explicit DTOs in P1-02 |
| G-28 | Transport | MQTT bridge test harness unusable in CI — blocks all transport coverage | **CRITICAL** | **PHASE 1** | \[object Object\] — TD-03 elevated. Injectable broker abstraction in P1-03 |
| G-29 | Transport | MQTT wildcard cnp/v1/nodes/+/+ misses cmd/out and multi-level topics | **CRITICAL** | **PHASE 1** | \[object Object\] — TD-02 elevated. Fix to \+/\# in P1-01 |
| G-30 | Architecture | Monolithic gateway boundary not formalised — re-architecture required to split later | **MEDIUM** | **PHASE 4** | \[object Object\] — service boundary formalisation in P4-06 |
| G-31 | Architecture | Capabilities model too static — no module version or command schema descriptors | **MEDIUM** | **PHASE 4** | \[object Object\] — forward compat field design in P4-06 |

# **Amended Technical Debt Register**

Items from CNP-SPEC-001 Appendix B are reproduced here with amended phase assignments and additional new items.

| TD-ID | Description | Effort | Original Priority | Amended Priority | Task |
| :---- | :---- | :---- | ----- | ----- | :---- |
| TD-01 |  | 1h | **MEDIUM** | **MEDIUM** | Add to SCHEMA\_SQL in P1 cleanup |
| TD-02 |  | 2h | **HIGH** | **CRITICAL** | P1-01 — Phase 1 hard fix |
| TD-03 |  | 1 day | **HIGH** | **CRITICAL** | P1-03 — Phase 1 hard gate |
| TD-04 |  | 1h | **CRITICAL** | **CRITICAL** | P1-02 — same-day patch before adding secret column |
| TD-05 |  | 3h | **HIGH** | **HIGH** | P3-01 — NTP integration |
| TD-06 |  | 1h | **MEDIUM** | **MEDIUM** | Replace with timer-based poll in P1 firmware review |
| TD-07 | No rate limiting on any endpoint — fleet flood risk | 4h | **MEDIUM** | **CRITICAL** | P1-04 \+ P1-05 — elevated to Phase 1 |
| TD-08 |  | 30m | **LOW** | **LOW** | P2 cleanup — adopt V2 pattern everywhere |
| TD-09 |  | 1 day | **NEW ITEM** | **CRITICAL** | P2-02 — added by this amendment |
| TD-10 |  | 0h | **NEW ITEM** | **CRITICAL** | Resolved by TD-02 / P1-01 fix |
| TD-11 |  | 30m | **NEW ITEM** | **HIGH** | Fix to \>=0.23 in P1-10 requirements update |

# **Forward Roadmap — CNP v1.5 and v2.0**

The following initiatives are out-of-scope for US+ but must be designed for from the start. The architectural decisions in Phases 1–4 should not close these doors.

## **v1.5 — Edge Automation Engine**

**Strategic value:** Shifts low-latency control loops to the node. Reduces dependence on continuous cloud connectivity. Enables graceful degradation. Codessa does not need a round-trip to the brain for every action.

Design target: central system defines policy, node executes simple local rules safely, node reports rule hits back to Codessa.

| Component | Description | Protocol hook |
| :---- | :---- | :---- |
| Rule deployment | Gateway sends automation rules to node NVS via config\_update message | `config_update + payload.module.rules[]` |
| Local rule engine | Firmware-side rule evaluator in Application::loop() — if condition → action | `BaseModule::handleLocalRule()` |
| Rule report | Node emits rule\_triggered event with rule\_id, condition\_value, action\_taken | `category: automation` |
| Policy guard | Gateway validates rules before deployment. Node enforces max rule count (e.g. 8). | `command category: configuration` |

| FWD | Design now: BaseModule should accept optional rules\[\] from config. Application::loop() should check rules before sending telemetry. This requires no protocol changes. |
| :---: | :---- |

## **v1.5 — Fleet Diagnostics Stream**

**Strategic value:** Moves fleet management from reactive (node failed) to predictive (node is about to fail). The data is already being collected — queue\_depth, free\_heap\_bytes, wifi\_rssi, command\_lag.

| Signal | Source | Predictive indicator |
| :---- | :---- | :---- |
| queue\_depth trend | heartbeat.queue\_depth | Rising queue \= delivery congestion or sensor storm approaching |
| free\_heap\_bytes trend | heartbeat.free\_heap\_bytes | Declining heap \= memory leak, will cause OOM reset |
| wifi\_rssi trend | heartbeat.wifi\_rssi | Weakening signal \= node approaching coverage boundary |
| command\_lag | command issued\_ts vs ack\_ts | Growing lag \= node under load or queue-backing up |
| auth\_fail\_rate | gateway rate\_limit events | Spike \= misbehaving clone, mis-provisioned node, or intrusion |
| heartbeat\_stability | last\_seen\_utc jitter | High jitter \= intermittent WiFi, watchdog resets |

## **v2.0 — Dynamic Node Capabilities**

**Strategic value:** Protocol becomes self-describing. The gateway can determine exactly which commands and telemetry fields are valid for each node without hardcoded assumptions. Module updates no longer require protocol version bumps.

Forward-compatible addition to `hello.payload.capabilities` — add these fields without breaking v1 consumers:

* `capabilities.modules[]` — array of {name, version} for each loaded BaseModule

* `capabilities.commands[]` — array of accepted command\_type strings with argument schemas

* `capabilities.telemetry[]` — array of reported telemetry field names and units

| FWD | Design now: BaseModule::describe() virtual method should be added in US+ so each module can self-report its command and telemetry surface. Not required in v1 but free to add. |
| :---: | :---- |

## **v2.0 — Event-Driven Ingestion Split**

**Strategic value:** The current monolithic gateway is a good start but will not scale to high event volume. The ingestion path (MQTT bridge → DB writes) should be separable from the query path (REST API) without re-architecture.

The internal boundary formalised in P4-06 is the preparation for this split. When the time comes:

* **Ingestion service:** GatewayMqttBridge \+ storage layer. Can scale horizontally. Stateless except for DB connection.

* **Command/control service:** Routes, command dispatcher, compat adapter. Depends on DB only, not on MQTT bridge.

* **Query/API service:** Read-only endpoints, dashboard, summary, fleet health. Can be replicated freely.

| FWD | Design now: P4-06 must define explicit Python interfaces (ABC or Protocol types) for the ingestion, control, and query layers. These interfaces make the split a refactor, not a re-architecture. |
| :---: | :---- |

# **Critical Path Summary**

The following tasks form the blocking sequence. Each depends on the previous. No parallelisation is possible across this chain.

| Step | Task | Blocks |
| :---- | :---- | :---- |
| 1 | P1-03 — Repair MQTT bridge test harness | All transport handler unit tests. P1-04 MQTT rate limit tests. P2 MQTT integration tests. |
| 2 | P1-01 — Fix MQTT wildcard subscription bug | cmd/out acks received. P3-05 command timeout reconciliation. P3-04 deduplication via ack loop. |
| 3 | P1-02 — Explicit response DTOs (no SELECT \*) | P2-02 per-node secret column can be safely added to nodes table. |
| 4 | P2-02 — Per-node secret column \+ provisioning spec | P1-07 auth middleware can validate against stored hashes. P3-02 HMAC signing. |
| 5 | P1-06 — Pydantic Envelope validation | P2-05 Pydantic alias layer. P2-03 compat adapter schema assertions. |
| 6 | P2-01 — TLS broker documentation | P2-07 auth on compat endpoints with TLS-protected transport. P4-01 PostgreSQL TLS path. |
| 7 | P3-01 — NTP timestamps | P3-02 HMAC signing (timestamp is part of signed payload). P3-04 dedup window validity. |

CNP-EXEC-002 v1.0  ·  Amended US+ Execution Plan  ·  Codessa Systems  ·  March 2026