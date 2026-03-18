#
## Summary
This plan addresses the two pre‑Sprint blockers surfaced by the analysis pipeline and then lays out the concrete, repo-grounded next steps for Sprint 1 (Phase 1 / EPIC‑01) execution:
1) unblock `/api/nodes` (currently 100% `ReadTimeout` under load), and
2) repair the Python test environment (`pytest-asyncio==1.1.0` is non-existent, so tests never ran).

It also locks an architectural decision needed before Phase 2: mount V1 compatibility endpoints at `/v1/compat/node/*` (matches CNP‑SPEC‑001’s endpoint table and minimizes legacy client churn).

## Current State Analysis (Evidence + Code Anchors)
### Benchmarks (already generated)
- `analysis/out/performance_summary.csv` shows:
  - `/api/nodes` 100% failures on both systems tested (errors are `ReadTimeout`) with 0 successful responses.
  - `/api/health` and `/health` show ~44–47% timeouts at 25 concurrency.

### Gateway (V2 / “prod” in the benchmark)
- The benchmark starts the gateway with `python -m uvicorn app.main:app --host 127.0.0.1 --port 8080` and `cwd=gateway/` ([analysis/run_comparative_analysis.py](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/analysis/run_comparative_analysis.py#L45-L52)).
- `/api/nodes` handler is implemented in [routes.py](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/api/routes.py#L25-L31) and currently does:
  - `aiosqlite.connect(settings.gateway_db_path)`
  - `SELECT * FROM nodes ORDER BY node_id`
- DB schema initialization exists and is called on lifespan startup ([main.py](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/main.py#L22-L32), [db.py:init_db](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/core/db.py#L85-L88)).
- There is currently only one pytest test ([test_api.py](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/tests/test_api.py#L1-L11)) and the test dependency pin is invalid:
  - [gateway/requirements.txt](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/requirements.txt#L8-L9) pins `pytest-asyncio==1.1.0` (does not exist), consistent with `quality_reports.json` showing `pytest_exit_code: 4` (no tests ran).

### MQTT wildcard bug (Phase 1 ticket P1‑01)
- MQTT bridge subscribes to `cnp/v1/nodes/+/+` ([mqtt_client.py](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/core/mqtt_client.py#L54-L56)).
- That pattern cannot match multi-level topics like `cnp/v1/nodes/{node_id}/cmd/out` (it only allows one segment after `{node_id}`), so `cmd/out` and similar multi-level topics are silently dropped. This aligns with TD‑02 / P1‑01 and the acceptance criteria in [CNP‑BOARD‑003](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/cnp_board_003_engineering_board.md#L75-L80).

### Compat mounting ambiguity (Phase 2)
- CNP‑SPEC‑001 enumerates V1 compat endpoints at `/v1/compat/node/*` ([cnp_v1_unified_spec.md](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/cnp_v1_unified_spec.md#L297-L301)).
- CNP‑EXEC‑002 describes “router at /v1/compat/*” ([cnp_exec_002_amended_execution_plan.docx.md](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/cnp_exec_002_amended_execution_plan.docx.md#L145-L149)), while the board mixes `/v1/compat/*` language with explicit `/v1/compat/node/commands/{node_id}` in acceptance criteria ([cnp_board_003_engineering_board.md](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/cnp_board_003_engineering_board.md#L152-L157)).

## Proposed Changes (Decision-Complete)
### 0) Pre‑Sprint Blocker: Make `/api/nodes` always respond (no hangs)
Goal: eliminate the “hang until client timeout” failure mode and make the endpoint safe under concurrency.

Changes:
- Add a single, shared DB connection helper that applies SQLite pragmas for concurrency and predictable behavior:
  - Enable WAL mode (reduces writer/reader blocking).
  - Set `busy_timeout` (fail fast with controlled error handling rather than indefinite waits).
  - Set row factory once.
  - Location: [gateway/app/core/db.py](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/core/db.py).
- Use that helper consistently in all DB access sites touched by request paths:
  - [gateway/app/api/routes.py](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/api/routes.py)
  - [gateway/app/core/registry.py](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/core/registry.py)
  - [gateway/app/core/storage.py](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/core/storage.py)
- Add an `ensure_db_initialized()` guard for the route layer:
  - Implementation: attempt a lightweight “schema present” check; if missing, call `await init_db(...)` once (process-local memoized).
  - This directly addresses the hypothesized “schema init race/missing init path” without relying on uvicorn lifespan ordering.
- Make `/api/nodes` and `/api/nodes/{node_id}` deterministic even on empty DB:
  - Return `[]` for list on empty DB.
  - Return 404 for missing node ID (already done).
- Add a regression test that would catch hangs:
  - `test_nodes_empty_returns_fast`: uses TestClient to call `/api/nodes` and asserts a 200 + JSON list.
  - If the handler blocks, this test will stall, immediately exposing the regression locally/CI.

Success criteria:
- Running the existing benchmark suite again yields non-empty `latencies_prod-nodes.csv` and `requests_ok > 0` for `/api/nodes`.
- `pytest` runs and includes the new `/api/nodes` tests.

### 1) Pre‑Sprint Blocker: Fix test dependency pin so pytest actually runs
Changes:
- Update [gateway/requirements.txt](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/requirements.txt#L8-L9):
  - Replace `pytest-asyncio==1.1.0` with `pytest-asyncio>=0.23`.

Success criteria:
- `pip install -r gateway/requirements.txt` succeeds.
- `pytest` executes (exit code 0 for passing suite, non-zero only for real failures).

### 2) Sprint 1 Critical Path (execute per board after baseline unblocked)
The board’s strict critical path is correct; after Steps 0–1:

#### P1‑03: Repair MQTT bridge test harness (injectable client factory)
Changes:
- Refactor [GatewayMqttBridge](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/core/mqtt_client.py#L14-L57) to accept an injectable `client_factory` returning an async context manager:
  - Default factory uses `asyncio_mqtt.Client(...)` as today.
  - Tests pass a fake in-memory broker/client implementing:
    - `subscribe(topic)`
    - `filtered_messages(pattern)` yielding messages
    - `publish(topic, payload, qos=...)`
- Add tests for each handler path (hello/heartbeat/event/error/ack/command_result) that:
  - Feed messages through the fake client.
  - Assert DB writes occur correctly (in-memory SQLite).

Success criteria:
- Gateway tests run in CI without requiring Mosquitto.
- Handler behavior is covered by deterministic unit tests.

#### P1‑01: Fix MQTT wildcard subscription bug
Changes:
- Update subscription and filtered message pattern in [mqtt_client.py](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/core/mqtt_client.py#L54-L56):
  - Replace `cnp/v1/nodes/+/+` with `cnp/v1/nodes/+/#` (matches board acceptance criteria).
- Add a test publishing to `cnp/v1/nodes/{node_id}/cmd/out` and asserting the message is ingested and dispatched.

Success criteria:
- Multi-level topics are received; `cmd/out` is no longer dropped.

#### P1‑02: Explicit response DTOs (no `SELECT *`, redact sensitive fields)
Changes:
- Replace `SELECT *` in:
  - [routes.py:list_nodes](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/api/routes.py#L25-L31)
  - [routes.py:get_node](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/api/routes.py#L34-L42)
  with explicit column lists.
- Introduce a `NodeResponse` Pydantic schema in [gateway/app/models/schemas.py](file:///c:/Projects/cnp_v1_starter_kit/cnp_v1_starter_kit/gateway/app/models/schemas.py) and return it from node endpoints.

Success criteria:
- Tests assert “excluded fields never appear” by checking response keys against a deny-list.

### 3) Add the missing “startup smoke test” as a first-class check
Motivation: `/api/nodes` 100% failures are exactly the class of issue that a startup+route smoke test catches early.

Changes:
- Add a pytest smoke test file:
  - Starts the FastAPI app via TestClient (startup + lifespan).
  - Calls `/api/health`, `/api/nodes`, and `/openapi.json` and asserts 200 (or 200+valid JSON).

Success criteria:
- A cold-start regression fails fast in CI before any deeper tests run.

### 4) Lock the V1 compat mount strategy now (Phase 2 pre-decision)
Decision:
- Standardize the compat router mount to `/v1/compat/node/*`.

Implementation implications (when Phase 2 begins):
- Ensure P2‑03 acceptance criteria wording aligns (it currently mixes `/v1/compat/*` and `/v1/compat/node/*`).
- Treat `/v1/compat/*` as a “router prefix” only in docs, while concrete endpoints include `/node/*`.

## Assumptions & Decisions
- Assume the `/api/nodes` failure mode is a hang (not a fast 500) because the benchmark errors are `ReadTimeout` and uvicorn access logs do not show completed `/api/nodes` requests.
- Decide to mitigate hangs first (WAL + busy_timeout + init guard + regression test) before attempting deeper perf tuning.
- Decide compat mount: `/v1/compat/node/*` (spec is the source of truth for concrete endpoint paths).

## Verification Steps (Post-Implementation)
- Install deps:
  - `python -m pip install -r gateway/requirements.txt`
- Run tests:
  - `python -m pytest -q` (from `gateway/`)
- Re-run analysis suite:
  - `python analysis/run_comparative_analysis.py`
  - Verify `analysis/out/latencies_prod-nodes.csv` contains successful rows and `performance_summary.csv` shows `requests_ok > 0` for `/api/nodes`.

