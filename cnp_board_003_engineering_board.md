

CODESSA NODE PROTOCOL v1

**Engineering Board**

| Based on | CNP-EXEC-002 — Amended US+ Execution Plan |
| :---- | :---- |
| Document No. | CNP-BOARD-003 |
| Version | 1.0 |
| Epics | 4  (EPIC-01 through EPIC-04) |
| Tickets | 34  (P1: 10 \+ corrections  ·  P2: 8  ·  P3: 7  ·  P4: 6  ·  Corrections: 3\) |
| Status | Ready for sprint assignment |
| Corrections | G-02 split (validation vs dedup)  ·  P1-07 interim token model clarified |

# **Corrections Applied from Review**

Two issues identified in the CNP-EXEC-002 review are corrected here before they become implementation ambiguity.

## **Correction 1 — G-02: Validation vs Deduplication Split**

**Problem:** G-02 in CNP-EXEC-002 assigned "Phase 1" and described both Pydantic rejection of missing message\_id and storage-level deduplication guarantees under the same entry. These are distinct concerns at different layers that land in different phases.

| Sub-gap | Concern | Phase | Ticket | What it does |
| :---- | :---- | ----- | :---- | :---- |
| G-02a | Envelope validation | **PHASE 1** | `P1-06` | Pydantic rejects any inbound message missing message\_id at the API boundary. No DB write occurs. Returns 422\. |
| G-02b | Storage deduplication | **PHASE 3** | `P3-04` | INSERT OR IGNORE indexed on `message_id`. Prevents double-write on node reconnect. Logs duplicate arrivals. |
| G-02c | Replay semantics | **PHASE 3** | `P3-04` | received\_at column enables dedup window queries. Duplicate detection is queryable and auditable. |

**Rule:** Phase 1 gives the guarantee "bad envelopes are rejected". Phase 3 gives the guarantee "valid envelopes are deduplicated in storage". These are additive, not overlapping.

## **Correction 2 — P1-07: Two-Stage Auth Model**

**Problem:** P1-07 (auth middleware, Phase 1\) and P2-02 (per-node secret provisioning, Phase 2\) appeared contradictory in the critical path: P2-02 was listed as blocking P1-07 validation against stored hashes, yet P1-07 is a Phase 1 deliverable. Engineering would stall on this.

The intended model is two-stage:

| Stage | Phase | Ticket | Token model | Upgrade path |
| :---- | ----- | :---- | :---- | :---- |
| Stage 1 — Bootstrap | **PHASE 1** | `P1-07` | Shared dev/bootstrap token per deployment zone, stored in `BOOTSTRAP_TOKEN` env var. All nodes use this token to register. Rate-limited and logged. | Replaced automatically when per-node secrets land in P2-02 |
| Stage 2 — Per-node | **PHASE 2** | `P2-02` | Unique secret issued per `node_id` at first registration. Stored as HMAC hash in `nodes.node_secret_hash`. Bootstrap token disabled for production zones. | Stage 3: HMAC signing in P3-02 uses this same secret |
| Stage 3 — Signed | **PHASE 3** | `P3-02` | Per-node secret used for HMAC-SHA256 `sig` field in envelope. Gateway verifies. Tampered messages rejected. | Full chain complete |

**Rule:** P1-07 does not depend on P2-02. P1-07 provides auth from day one using a bootstrap token. P2-02 upgrades that auth to per-node secrets. P3-02 then adds message signing on top. The three stages are sequential upgrades, not blockers.

# **Epic Map**

| Epic | Phase | Title | Mandate | Tickets | Weeks |
| :---- | ----- | :---- | :---- | :---- | :---- |
| `EPIC-01` | **PHASE 1** | Stabilise the Core | Correct, safe, testable before any compatibility or scale work | 11 | 1–2 |
| `EPIC-02` | **PHASE 2** | Secure Compatibility Layer | Legacy nodes connect safely. Security structure established. | 8 | 3–4 |
| `EPIC-03` | **PHASE 3** | Operational Hardening | Message correctness and fleet behaviour are deterministic. | 7 | 5–6 |
| `EPIC-04` | **PHASE 4** | Scale and Maintainability | System is ready for larger fleet rollout and sustained ops. | 6 | 7–8 |

## **Dependency Critical Path**

The following sequence is strictly ordered. No task in row N can begin until row N-1 is complete. Parallelisation is possible within a row but not across it.

| Step | Ticket | Task | Unlocks |
| :---- | :---- | :---- | :---- |
| 1 | `P1-03` | Repair MQTT bridge test harness | All transport handler tests · P1-04 MQTT rate limit tests · P2 MQTT integration tests |
| 2 | `P1-01` | Fix MQTT wildcard subscription bug | cmd/out acks received · P3-05 command timeout · P3-04 deduplication via ack loop |
| 3 | `P1-02` | Explicit response DTOs (no SELECT \*) | P2-02 per-node secret column can land safely on nodes table |
| 4 | `P1-06` | Pydantic Envelope validation | P2-05 alias layer · P2-03 compat adapter schema assertions |
| 5 | `P1-07` | Bootstrap token auth middleware | P2-03 compat adapter inherits same gate · P2-07 auth on compat endpoints |
| 6 | `P2-01` | TLS broker documentation | P2-07 compat endpoints on TLS transport · P4-01 PostgreSQL TLS path |
| 7 | `P2-02` | Per-node secret \+ provisioning spec | P1-07 upgrade to hashed validation · P3-02 HMAC signing |
| 8 | `P3-01` | NTP-backed timestamps | P3-02 HMAC signing (timestamp in signed payload) · P3-04 dedup window validity |

| `EPIC-01` PHASE 1 | Stabilise the Core 5 gates | Weeks 1–2  ·  Mandate: correct, safe, testable before any other work begins Exit gates: 075985 |
| :---: | :---- | ----- |

**Exit condition:** MQTT bridge starts and handler tests pass in CI. Rate limiting is live and observable. Secrets are redacted from all API responses. Malformed messages are rejected at the boundary. Gateway coverage ≥ 60%.

| `P1-01` | Fix MQTT wildcard subscription bug | EPIC-01 | CRITICAL |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **2h** | Blocks: P3-05, P3-04 | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| `cnp/v1/nodes/+/+` subscription replaced with `cnp/v1/nodes/+/#` Gateway receives messages on `cmd/out` topic. Verified by test publishing to that path. Gateway receives messages on `errors` (multi-level) topic. Verified by test. No existing subscriptions broken. hello/heartbeat/event still received. Handler dispatch table updated to route all new topics correctly. |  |  |  |

| `P1-02` | Explicit response DTOs — redact sensitive fields | EPIC-01 | CRITICAL |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **2h** | Blocks: P2-02 | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| New `NodeResponse` Pydantic model defined. Contains only public fields: node\_id, node\_name, node\_type, zone, status, firmware\_version, capabilities\_json, last\_seen\_utc, battery\_pct, wifi\_rssi, queue\_depth. `node_secret_hash`, `metadata_json`, and any future auth columns excluded by model definition, not by filter logic. GET /api/nodes and GET /api/nodes/{id} return `NodeResponse`. Verified: response JSON contains zero excluded fields. Automated assertion in test\_nodes.py: iterate response keys, assert none match exclusion list. SELECT \* is removed from all node-returning queries in routes.py. |  |  |  |

| `P1-03` | Repair MQTT bridge test harness | EPIC-01 | CRITICAL |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **1d** | Blocks: ALL transport tests | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| `GatewayMqttBridge` accepts an injectable client factory parameter (default: real asyncio-mqtt Client). Mock broker fixture available: in-memory pub/sub implementation usable without a live Mosquitto instance. Test fixture wires mock broker into bridge. Bridge starts, subscribes, and dispatches in CI with **zero external dependencies**. Handler tests for hello, heartbeat, event, error, ack, command\_result all pass using mock broker fixture. CI workflow runs gateway tests without any MQTT broker service dependency in the runner. readme updated: documents how to run tests locally with and without a real broker. |  |  |  |

| `P1-04` | HTTP rate limiting | EPIC-01 | CRITICAL |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **4h** | Blocks: — | Note: Resolves TD-07 |
| **ACCEPTANCE CRITERIA** |  |  |  |
| Per-node\_id rolling window: 60 requests/60s. Excess returns HTTP 429 with Retry-After header. Per-source-IP rolling window: 200 requests/60s. Same breach behavior. Global rolling window: 2000 requests/60s. Breach triggers alert log event. Every breach emits a structured log event with `event_type`: rate\_limit.http.\* and node\_id, source\_ip, window, count fields. Rate limit state is in-process (no Redis required in Phase 1). Integration test: send 100 identical requests from one node\_id, assert 40+ return 429, assert other node\_id unaffected. |  |  |  |

| `P1-05` | MQTT rate limiting and backpressure | EPIC-01 | CRITICAL |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **4h** | Blocks: — | Note: Resolves TD-07 MQTT side |
| **ACCEPTANCE CRITERIA** |  |  |  |
| Per client-ID publish cap: 10 msg/sec sustained. Burst allowance: 50 msg/sec for up to 5s. Messages exceeding cap are dropped at bridge ingestion before parsing. Dropped count logged. After 3 invalid-message breaches within 60s from one client-ID: disconnect that client and quarantine for 5 minutes. Breach events emitted as `rate_limit.mqtt.*` log entries with client\_id, topic, breach\_count, action fields. Rate-limited nodes do not degrade bridge throughput for other nodes. Verified by concurrent load test. Quarantine list is in-memory. Clears on gateway restart (acceptable for Phase 1). |  |  |  |

| `P1-06` | Pydantic Envelope validation — reject at boundary | EPIC-01 | CRITICAL |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **4h** | Blocks: P2-05 | Note: Resolves G-09, G-02a |
| **ACCEPTANCE CRITERIA** |  |  |  |
| `Envelope` Pydantic model validates all inbound MQTT and HTTP messages before any DB write or dispatch occurs. Missing `message_id`: rejected with 422\. No write. Structured error: field=message\_id, issue=required. Invalid `node_id` pattern (not ^\[a-z0-9-\]{3,64}$): rejected with 422\. Wrong `protocol_version` value: rejected with 422\. `qos` not 0 or 1: rejected with 422\. Parametrised test with 12 invalid fixture messages: all rejected, none written to DB. Valid canonical message passes through and is written correctly. MQTT invalid messages increment the invalid-message breach counter (feeds P1-05 quarantine logic). |  |  |  |

| `P1-07` | Bootstrap token auth middleware — Stage 1 | EPIC-01 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend / Security** | Effort: **3h** | Blocks: — | Note: Correction applied: two-stage model |
| **ACCEPTANCE CRITERIA** |  |  |  |
| FastAPI middleware validates `X-CNP-Node-Token` header on all `/api/node/*` and future `/v1/compat/*` routes. Stage 1 token source: `BOOTSTRAP_TOKEN` environment variable. If env var absent, middleware raises configuration error on startup (fail-fast). Missing or invalid token returns HTTP 401\. Response body: {error: unauthorized, hint: set X-CNP-Node-Token}. Auth failure is logged with source\_ip, node\_id (if present in body), and timestamp. Bootstrap token is rate-limited to 30 registrations/minute (prevents enumeration). Middleware design is token-source-agnostic: upgrading to per-node hash lookup in P2-02 requires only swapping the validation function, not the middleware structure. Unit test: valid token passes, missing token 401, wrong token 401, expired (future) token handled gracefully. |  |  |  |

| `P1-08` | Port V1 SQL views to V2 schema | EPIC-01 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **2h** | Blocks: — | Note: Resolves G-15 |
| **ACCEPTANCE CRITERIA** |  |  |  |
| Four views added to `db.py` SCHEMA\_SQL: `v_node_status`, `v_recent_alerts`, `v_pending_commands`, `v_event_summary`. All column references updated to V2 names: ts\_utc, body\_json, arguments\_json, battery\_pct. v\_node\_status includes: node\_id, node\_name, node\_type, zone (from metadata\_json), status, battery\_pct, wifi\_rssi, last\_seen\_utc, seconds\_since\_seen, firmware\_version. v\_recent\_alerts filters: priority IN (high, critical) AND ts\_utc \>= now-24h. Joins nodes for zone context. v\_pending\_commands returns commands WHERE status=pending ordered by issued\_ts\_utc ASC. v\_event\_summary aggregates event\_count and last\_event per node\_id, category for last 24h. Integration test: seed nodes \+ events \+ commands, query each view, assert expected row counts and values. |  |  |  |

| `P1-09` | Heartbeat trim trigger | EPIC-01 | MEDIUM |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **1h** | Blocks: — | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| AFTER INSERT trigger on `heartbeats` table: delete oldest rows beyond 1000 per node\_id. Trigger uses subquery selecting 1000 most recent IDs for that node\_id, deletes the rest. Test: insert 1010 heartbeats for one node. Assert table contains exactly 1000 rows for that node after trigger fires. Second node unaffected: insert 50 heartbeats for node\_2. Assert 50 rows retained. Trigger fires on every insert, not on batch. No scheduled job required. |  |  |  |

| `P1-10` | Expand pytest coverage — gateway Phase 1 target: 60% | EPIC-01 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **1d** | Blocks: — | Note: Resolves TD-11 |
| **ACCEPTANCE CRITERIA** |  |  |  |
| Fix `pytest-asyncio` version in requirements.txt: `pytest-asyncio>=0.23`. Current `1.1.0` is non-existent (TD-11). Test files created: test\_nodes.py, test\_events.py, test\_commands.py, test\_validation.py, test\_rate\_limiting.py. test\_nodes.py: list, get, 404, field exclusion assertion (P1-02 contract). test\_validation.py: 12 invalid envelope fixtures all rejected at boundary with correct 422 shape. test\_rate\_limiting.py: HTTP throttle at 60/min, second client unaffected, breach event logged. Coverage report published as CI artifact. Gate: 60% minimum. Merge blocked below threshold. All tests use in-memory SQLite fixture (no file I/O required). |  |  |  |

| `EPIC-02` PHASE 2 | Secure Compatibility Layer 4 gates | Weeks 3–4  ·  Mandate: legacy nodes connect safely; security structure established before field deployment Exit gates: 5B21B6 |
| :---: | :---- | ----- |

**Exit condition:** V1 migration DDL runs with zero data loss. V1 compat integration test (11 steps) passes in CI. TLS broker test passes with self-signed cert. Coverage ≥ 75%.

| `P2-01` | TLS broker documentation and gateway TLS path | EPIC-02 | CRITICAL |
| :---- | :---- | ----- | ----- |
| Owner: **Ops / Backend** | Effort: **1d** | Blocks: — | Note: Resolves G-21 partial |
| **ACCEPTANCE CRITERIA** |  |  |  |
| Mosquitto TLS configuration documented: generate CA, server cert, client cert. Steps tested on clean install. `WiFiClientSecure` path added to `TransportMqtt`. Activated by `MQTT_TLS_ENABLED=true` env var. Gateway settings: `MQTT_TLS_CA_PATH`, `MQTT_TLS_CERT_PATH`, `MQTT_TLS_KEY_PATH` env vars documented. Test with self-signed cert: broker rejects plaintext connection, accepts TLS connection. TLS configuration guide covers: development self-signed, Let's Encrypt for production, client certificate rotation. examples/mosquitto.conf updated with TLS stanza commented and annotated. |  |  |  |

| `P2-02` | Per-node secret column and provisioning spec — Stage 2 auth | EPIC-02 | CRITICAL |
| :---- | :---- | ----- | ----- |
| Owner: **Backend / Security** | Effort: **1d** | Blocks: — | Note: Resolves G-21. Upgrades P1-07 |
| **ACCEPTANCE CRITERIA** |  |  |  |
| `node_secret_hash` TEXT column added to nodes table via migration DDL. Column is nullable (bootstrap-registered nodes have NULL until provisioned). Provisioning flow: on first registration, gateway generates a cryptographically random 32-byte secret. Returns plain secret ONCE in register\_ack payload. Stores HMAC-SHA256 hash of secret. P1-07 middleware upgraded: if node\_secret\_hash IS NOT NULL, validate X-CNP-Node-Token as HMAC against stored hash. If NULL, fall back to bootstrap token. Provisioning API: POST /api/nodes/{id}/rotate-secret — generates new secret, returns once, invalidates old. Bootstrap token is disabled for any zone with all nodes provisioned (BOOTSTRAP\_DISABLED env flag). Documentation: node provisioning workflow, QR-code delivery pattern, USB provisioning fallback. Test: register node with bootstrap token, provision secret, subsequent request with plain bootstrap token rejected, HMAC token accepted. |  |  |  |

| `P2-03` | V1 HTTP compat adapter | EPIC-02 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **1d** | Blocks: — | Note: Resolves G-01, G-04, G-17, G-18, G-19 |
| **ACCEPTANCE CRITERIA** |  |  |  |
| New FastAPI router mounted at `/v1/compat/*`. All 5 endpoints: hello, heartbeat, event, error, command\_result. Command poll: GET /v1/compat/node/commands/{node\_id}. Each endpoint accepts V1 envelope format and translates to V2 before any storage or dispatch call. Field translations applied (full map in CNP-EXEC-002): protocol→protocol\_version, timestamp→ts\_utc, params→arguments, event\_id→message\_id, error\_code→code+domain+severity. ULID `message_id` generated at gateway for any V1 message missing it. `qos` defaulted to 0\. `delivery_mode` defaulted to fire\_and\_forget. `requires_ack` defaulted to false. Every V1 key translation emits a `DEPRECATION_V1_KEY` structured log entry with original\_key, canonical\_key, node\_id. Auth: compat endpoints use same P1-07 middleware (same token gate, no weaker legacy path). |  |  |  |

| `P2-04` | V1 → V2 database migration DDL | EPIC-02 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **4h** | Blocks: — | Note: Resolves G-13, G-14 |
| **ACCEPTANCE CRITERIA** |  |  |  |
| migrate.py CLI: \--dry-run flag, per-table progress reporting, rollback checkpoint, post-migration integrity check. ALTER TABLE nodes ADD COLUMN scripts for all 9 V2 columns with safe defaults: `device_uid DEFAULT ""`, `hardware_model DEFAULT "unknown"`, boot\_reason, config\_version, free\_heap\_bytes, queue\_depth DEFAULT 0, supports\_ota DEFAULT 0, tags\_json DEFAULT "\[\]", metadata\_json DEFAULT "{}". Status enum expansion: existing `offline` rows NOT changed. New states (unknown, registering, blocked, retired) available but not auto-assigned. Battery column: `battery` INT → `battery_pct REAL`. Migration casts existing INT values. \-1 sentinel converted to NULL. acks table created if not exists. Dry-run test on 10k-row V1 fixture: zero errors reported. Live run on same fixture: row counts match. Rollback restores original schema and data. |  |  |  |

| `P2-05` | Pydantic alias layer — accept V1 key names | EPIC-02 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **2h** | Blocks: — | Note: Resolves G-04, MC-01, MC-02 |
| **ACCEPTANCE CRITERIA** |  |  |  |
| `model_validator(mode="before")` on Envelope: if `protocol` present and `protocol_version` absent, rename. If `timestamp` present and `ts_utc` absent, rename. Normalise `ts_utc` to Z suffix if not present. If V1 key detected, emit `DEPRECATION_V1_KEY` log entry with original\_key and node\_id. V2 canonical keys are never aliased back. Alias is inbound-only, one-directional. Test: V1 envelope with protocol+timestamp fields passes Pydantic validation and is stored with V2 key names. Test: V2 envelope unchanged. Test: both keys present — V2 wins, V1 logged as redundant. |  |  |  |

| `P2-06` | Port test\_flow.sh to pytest integration suite | EPIC-02 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **4h** | Blocks: — | Note: Resolves G-23 |
| **ACCEPTANCE CRITERIA** |  |  |  |
| test\_integration.py using httpx.AsyncClient with real in-memory SQLite. No MQTT broker required. 11 test steps execute in order (depends\_on pattern): health → hello (V1 compat) → heartbeat → telemetry event → alert event → error → issue command → poll command (V1 format) → ack → summary endpoint → offline detection (clock advance). Each step asserts: HTTP status, response schema validity, DB state after write. Offline detection step: manually set last\_seen\_utc to 200s ago, trigger mark\_offline\_nodes(), assert status=offline. test\_flow.sh retained for manual smoke testing but no longer authoritative. Integration test added to CI as separate job: runs after unit tests, publishes pass/fail status. |  |  |  |

| `P2-07` | Auth enforcement on compat endpoints | EPIC-02 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend / Security** | Effort: **2h** | Blocks: — | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| Compat router applies P1-07 middleware. No weaker auth for legacy nodes than V2 nodes. V1 nodes provisioned with bootstrap token in Stage 1\. Upgraded to per-node secret in Stage 2 (P2-02) without reflash. Auth failure on compat endpoints returns 401 with V1-friendly response body (plain JSON, no Pydantic envelope required). Test: V1 hello with no token returns 401\. V1 hello with bootstrap token accepted. V1 hello with wrong token rejected. |  |  |  |

| `P2-08` | API summary and fleet status endpoints | EPIC-02 | MEDIUM |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **2h** | Blocks: — | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| GET /api/summary returns: total\_nodes, online\_count, offline\_count, degraded\_count, alerts\_24h, errors\_24h, pending\_commands. Backed by V1 SQL views from P1-08. GET /api/fleet/status returns per-zone breakdown using `metadata_json->>"$.zone"` with counts. Both endpoints use NodeResponse DTO chain — no raw column exposure. test\_nodes.py: seed 3 nodes (2 online, 1 offline), 2 alerts, assert summary values exactly. |  |  |  |

| `EPIC-03` PHASE 3 | Operational Hardening 4 gates | Weeks 5–6  ·  Mandate: message correctness and fleet behaviour are deterministic Exit gates: 166534 |
| :---: | :---- | ----- |

**Exit condition:** Duplicate message\_id produces exactly one row. Command with 5s timeout transitions to timeout within 10s. config\_update applied without reboot. Coverage ≥ 80%.

| `P3-01` | NTP-backed timestamps in firmware | EPIC-03 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Firmware** | Effort: **3h** | Blocks: — | Note: Resolves TD-05 |
| **ACCEPTANCE CRITERIA** |  |  |  |
| Integrate `arduino-libraries/NTPClient` in `Application::begin()`. Attempt NTP sync, timeout 5s. `Protocol::nowUtc()` returns NTP time when available, uptime-derived stub when not. Fallback logged as `NTP_FALLBACK` warning. NTP server configurable via config (default: pool.ntp.org). Sync retried every 1h. All firmware messages including hello, heartbeat, event now carry valid UTC timestamps (not empty string). Verified by checking `ts_utc` field in received messages at gateway. Firmware simulation test (desktop target): mock NTP returns known timestamp, assert Protocol::nowUtc() returns that value. |  |  |  |

| `P3-02` | HMAC-SHA256 message signing — Stage 3 auth | EPIC-03 | MEDIUM |
| :---- | :---- | ----- | ----- |
| Owner: **Firmware / Backend** | Effort: **1d** | Blocks: — | Note: Resolves G-21 complete |
| **ACCEPTANCE CRITERIA** |  |  |  |
| Firmware: optional HMAC-SHA256 of canonical payload string using per-node secret from NVS. Gate on settings.enableSig (default false). Signed value placed in envelope `sig` field. Node ID and timestamp are included in signed payload to prevent replay. Gateway: verify sig when present. Log HMAC\_VERIFY\_FAIL with node\_id, message\_id, reject message. Missing sig field accepted (Phase 3 is opt-in). NVS secret key set during provisioning (P2-02 bootstrap flow). Key rotation triggers P2-02 rotate-secret flow. Test: message with correct sig accepted. Message with tampered payload rejected. Message with no sig accepted (opt-in mode). Phase 4 can make sig mandatory per zone via config\_update. |  |  |  |

| `P3-03` | config\_update MQTT handler in firmware | EPIC-03 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Firmware** | Effort: **4h** | Blocks: — | Note: Resolves G-24 |
| **ACCEPTANCE CRITERIA** |  |  |  |
| Firmware subscribes to `cnp/v1/nodes/{id}/config` at startup. On receipt: validate config\_version \> current stored in NVS. If stale, log and ignore. Apply heartbeat\_interval\_sec and telemetry\_interval\_sec immediately without reboot. Persist to NVS. Ack sent with config\_version applied and applied\_fields array. Firmware simulation test: send config\_update with heartbeat\_interval\_sec=10, assert next heartbeat arrives within 15s. Assert `config_version` increments in NVS. Gateway: POST /api/nodes/{id}/config publishes config\_update to MQTT and updates node\_config table. |  |  |  |

| `P3-04` | Storage-level deduplication — message\_id uniqueness | EPIC-03 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **3h** | Blocks: — | Note: Resolves G-02b, G-02c |
| **ACCEPTANCE CRITERIA** |  |  |  |
| `INSERT OR IGNORE` used in insert\_event, insert\_error, insert\_ack — indexed on `message_id UNIQUE` constraint. `received_at` column added to events, errors, acks tables. Set to gateway receive time (not node ts\_utc). Enables dedup window queries. Duplicate arrival logged: structured log entry with message\_id, node\_id, original\_received\_at, duplicate\_received\_at. Test: send same event twice (same message\_id). Assert exactly one row in events. Assert duplicate log entry emitted. Test: send two events with different message\_ids. Assert two rows. Assert no duplicate log. Dedup window query: SELECT message\_id, count(\*) FROM events GROUP BY message\_id HAVING count(\*) \> 1 must return 0 rows after test suite. |  |  |  |

| `P3-05` | Command timeout reconciliation | EPIC-03 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **3h** | Blocks: — | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| Background task scans commands WHERE status IN (queued, pending) every 30s. For each: if now() \- issued\_ts\_utc \> timeout\_ms, set status=timeout. Emit timeout event to `cnp/v1/nodes/{node_id}/events` topic with category=system, priority=normal. API: timed-out commands are visible via GET /api/nodes/{id}/commands/{cmd\_id} with status=timeout and completed\_ts\_utc set. Test: issue command with timeout\_ms=2000, advance clock 3s (or mock task scheduler), assert status=timeout. Assert no status change for command with timeout\_ms=60000. |  |  |  |

| `P3-06` | EventQueue retry semantics in firmware | EPIC-03 | MEDIUM |
| :---- | :---- | ----- | ----- |
| Owner: **Firmware** | Effort: **4h** | Blocks: — | Note: Resolves G-07 complete |
| **ACCEPTANCE CRITERIA** |  |  |  |
| EventQueue: retry failed sends up to 3 times with exponential backoff (1s, 2s, 4s delays). After 3 failures: mark message as dead\_letter. Do not drop silently. Dead-letter count included in heartbeat `queue_depth` and reported separately as `dead_letter_count` field. Dead-letter queue bounded at 16 entries. If full, oldest dead-letter dropped (log warning). Firmware simulation test: inject transport failure for 3 attempts, assert message moves to dead\_letter. Inject transport recovery, assert normal messages send. |  |  |  |

| `P3-07` | Offline timeout hardening — per-node granularity | EPIC-03 | MEDIUM |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **2h** | Blocks: — | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| `mark_offline_nodes` uses per-node `offline_after_sec` from nodes table rather than global `settings.offline_after_seconds`. On transition online→offline: emit fleet\_event log entry with node\_id, zone, last\_seen\_utc, reason=heartbeat\_timeout. fleet\_event queryable: GET /api/fleet/events?type=node\_offline\&since=\<iso\>. Test: set node offline\_after\_sec=10, advance clock 15s, trigger watcher, assert status=offline. Second node with offline\_after\_sec=300 unchanged. |  |  |  |

| `EPIC-04` PHASE 4 | Scale and Maintainability 3 gates | Weeks 7–8  ·  Mandate: ready for larger fleet rollout and sustained ops Exit gates: 9A3412 |
| :---: | :---- | ----- |

**Exit condition:** benchmark\_gateway.py reports ≥500 events/sec. CI blocks PR on failing test, coverage below 80%, lint error, or migration DDL syntax error. migrate.py dry-run on 10k V1 fixture completes with zero errors.

| `P4-01` | PostgreSQL adapter | EPIC-04 | MEDIUM |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **1d** | Blocks: — | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| DB layer abstracted behind a thin adapter interface (Python `Protocol` type). aiosqlite and asyncpg share the same interface. Activated by `GATEWAY_DB_URL` env var: if starts with `postgresql://`, use asyncpg. Otherwise default to aiosqlite. All existing SQL (including views from P1-08) runs unchanged on both backends. Migration DDL from P2-04 tested against PostgreSQL 14\. CI runs tests against both SQLite (default) and PostgreSQL (docker service) on main branch only. |  |  |  |

| `P4-02` | CI/CD pipeline quality gates | EPIC-04 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **DevOps** | Effort: **1d** | Blocks: — | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| GitHub Actions workflow: triggers on PR and push to main. Gates (all must pass): `ruff check gateway/`, `mypy gateway/`, `pytest --cov=app --cov-fail-under=80`, firmware `pio ci` build check, schema validation script. Migration DDL dry-run against in-memory SQLite on every PR (catches syntax errors before merge). Coverage report uploaded as PR artifact. Coverage delta shown in PR comment. Test to verify gate: deliberately introduce lint error, assert CI fails. Revert, assert CI passes. |  |  |  |

| `P4-03` | Load and soak testing | EPIC-04 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend / DevOps** | Effort: **1d** | Blocks: — | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| extend benchmark\_gateway.py: 500 events/sec sustained throughput test for 60s. Measure p50/p95/p99 write latency. 10k simulated node registration test. Assert all registrations succeed, no DB lock errors. 1-hour soak at 100 concurrent nodes (simulation). Assert zero message loss, zero gateway crashes. Target: ≥500 events/sec sustained. p95 SQLite WAL write \<2ms. p99 MQTT LAN round-trip \<10ms. Results published as CI artifact. Regression gate: if p95 degrades \>20% from baseline, block merge. |  |  |  |

| `P4-04` | Migration tooling — migrate.py CLI | EPIC-04 | HIGH |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **4h** | Blocks: — | Note: — |
| **ACCEPTANCE CRITERIA** |  |  |  |
| migrate.py: \--dry-run flag prints planned DDL changes without executing. \--source path to V1 SQLite DB. Per-table progress: NODES: 342 rows processed, 342 migrated, 0 errors. Rollback checkpoint: snapshot taken before migration. \--rollback flag restores snapshot. Post-migration integrity check: row counts match pre-migration counts. Spot-check sample of values. Dry-run test on 10k-row V1 fixture: zero errors. Live run: row counts match. Rollback: original restored. |  |  |  |

| `P4-05` | Fleet diagnostics surface | EPIC-04 | MEDIUM |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **4h** | Blocks: — | Note: Blue-sky pulled forward |
| **ACCEPTANCE CRITERIA** |  |  |  |
| GET /api/fleet/health: per-node aggregation of queue\_depth trend, free\_heap\_bytes trend, wifi\_rssi trend, command lag (issued→ack delta), auth\_fail\_rate. Trend: last 10 data points from heartbeats table. Exposed as {min, max, mean, last} per metric. Threshold flags: queue\_depth \> 10 \= WARNING. free\_heap\_bytes declining 3 consecutive reads \= WARNING. wifi\_rssi \< \-80 \= WARNING. Test: seed heartbeat history with declining free\_heap\_bytes pattern, assert fleet/health returns WARNING for that node, OK for nodes with stable values. |  |  |  |

| `P4-06` | Service boundary formalisation | EPIC-04 | MEDIUM |
| :---- | :---- | ----- | ----- |
| Owner: **Backend** | Effort: **4h** | Blocks: — | Note: Prepares for CNP v2 microservice split |
| **ACCEPTANCE CRITERIA** |  |  |  |
| Define three Python `Protocol` (structural typing) interfaces: `IngestionBus`, `CommandController`, `QueryService`. Existing gateway classes annotated to satisfy these interfaces. No behaviour changes. Document: which classes belong to each service boundary, what the interface contract is, what the split migration path looks like. BaseModule::describe() virtual method added to firmware (returns module name, version, command list, telemetry field list). Not required by Application in v1 but available for v2 capability descriptors. mypy confirms all classes correctly satisfy their Protocol interfaces. Verified in CI. |  |  |  |

# **Owner Assignment Summary**

Recommended assignment groupings. Adjust to your actual team structure.

| Owner | Tickets | Total effort | Notes |
| :---- | :---- | :---- | :---- |
| Backend | P1-01, P1-02, P1-03, P1-04, P1-06, P1-07, P1-08, P1-09, P1-10, P2-03, P2-04, P2-05, P2-06, P2-08, P3-04, P3-05, P3-07, P4-01, P4-04 | \~11d | Largest block — split across 2 engineers if possible |
| Security | P1-07 (co-own), P2-02, P2-07 | \~2.5d | Owns provisioning spec and auth upgrade path |
| Firmware | P3-01, P3-02 (co-own), P3-03, P3-06, P4-06 (BaseModule) | \~2.5d | Desktop simulation tests acceptable for Phases 3–4 |
| Ops | P2-01 | \~1d | TLS documentation and broker hardening |
| DevOps | P4-02, P4-03 | \~2d | CI pipeline and load testing |
| Backend+Security | P1-05 (MQTT rate limit), P3-02 (HMAC, co-own) | \~1.5d | Joint ownership — security domain \+ gateway implementation |

# **Sprint Suggestion — 4 × 2-Week Sprints**

The following sprint breakdown assumes 2 engineers. Adjust ticket assignment if more or fewer resources are available.

| Sprint | Phase | Tickets | Sprint goal |
| :---- | ----- | :---- | :---- |
| Sprint 1 | **PHASE 1** | P1-03, P1-01, P1-02, P1-06 | Bridge testable in CI. Critical bugs fixed. DTOs safe. Validation live. This sprint unblocks all later work. |
| Sprint 2 | **PHASE 1** | P1-04, P1-05, P1-07, P1-08, P1-09, P1-10 | Rate limits live. Auth gate live (Stage 1). SQL views ported. Coverage ≥ 60%. Phase 1 exit gates met. |
| Sprint 3 | **PHASE 2** | P2-01, P2-02, P2-03, P2-04, P2-05 | TLS documented. Per-node secrets (Stage 2 auth). V1 compat adapter live. Migration DDL ready. |
| Sprint 4 | **PHASE 2** | P2-06, P2-07, P2-08 | V1 integration test in CI. Compat auth enforced. Summary endpoints live. Phase 2 exit gates met. |
| Sprint 5 | **PHASE 3** | P3-01, P3-03, P3-04, P3-05 | NTP timestamps. config\_update live. Deduplication guaranteed. Command timeouts deterministic. |
| Sprint 6 | **PHASE 3** | P3-02, P3-06, P3-07 | HMAC signing (opt-in). EventQueue retry semantics. Per-node offline detection. Phase 3 exit gates met. |
| Sprint 7 | **PHASE 4** | P4-01, P4-02, P4-03 | PostgreSQL path. CI quality gates. Load and soak tests. |
| Sprint 8 | **PHASE 4** | P4-04, P4-05, P4-06 | Migration CLI. Fleet diagnostics. Service boundaries formalised. Phase 4 exit gates met. |

CNP-BOARD-003 v1.0  ·  Engineering Board  ·  Codessa Systems  ·  March 2026