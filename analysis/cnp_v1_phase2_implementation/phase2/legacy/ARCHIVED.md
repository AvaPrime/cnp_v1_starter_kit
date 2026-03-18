# Legacy — Archived Root-Level Files

> **These files are preserved for reference only.**
> The production gateway is in [`gateway/`](../gateway/). Do not run or import these files in a new deployment.

---

## Why these files exist

CNP v1 was prototyped as a flat single-directory Python application. After Sprint 1 the codebase was restructured into the modular `gateway/app/` layout (FastAPI app factory, layered `core/`, `api/`, `models/` packages). The root-level files were retained for archaeological reference during Sprint 2 and are now archived here.

---

## File inventory

### Gateway — Legacy Flat System (`v0.1.x`)

| File | Production equivalent | Notes |
|---|---|---|
| `gateway.py` | `gateway/app/` (entire package) | 579-line monolith. Entry point was `python gateway.py`. Includes sync SQLite via `sqlite3`, no WAL mode applied consistently. |
| `main.py` | `gateway/app/main.py` | FastAPI app factory — early iteration |
| `api.py` | `gateway/app/api/routes.py` | Route handlers — flat version |
| `routes.py` | `gateway/app/api/routes.py` | Intermediate refactor, superseded |
| `admin.py` | `gateway/app/api/admin.py` | Admin endpoints — **no auth** in this version |
| `compat.py` | `gateway/app/api/compat.py` | V1 compatibility shim |
| `auth.py` | `gateway/app/core/auth.py` | HMAC auth — bootstrapped from this file |
| `db.py` | `gateway/app/core/db.py` | SQLite init — no WAL pragma |
| `models.py` | `gateway/app/models/schemas.py` | Pydantic models |
| `schemas.py` | `gateway/app/models/schemas.py` | Schema aliases |
| `mqtt_client.py` | `gateway/app/core/mqtt_client.py` | MQTT bridge — had wildcard bug (`+/+`) |
| `rate_limit.py` | `gateway/app/core/rate_limit.py` | Sliding window rate limiter |
| `conftest.py` | `gateway/tests/conftest.py` | Root-level test fixtures (wrong location) |

### Operational Intelligence — CNP-OPS-004 (`Unreleased / Phase O2`)

These modules implement the anomaly detection, fleet scoring, and reflex healing system specified in `CNP-OPS-004_operational_intelligence_layer.md`. They are not wired into the production gateway — integration is planned for Phase 3 / EPIC-02.

| File | Purpose |
|---|---|
| `detector.py` | Anomaly detection engine — rolling heartbeat windows, rules A-001/A-002/A-003/A-005/A-010 |
| `scoring.py` | Per-node health score (reliability 35%, performance 25%, security 20%, maintainability 10%, responsiveness 10%) |
| `healer.py` | Reflex healing engine — autonomous remediation actions triggered by anomaly queue |
| `summaries.py` | Fleet summary aggregation layer |
| `rules.py` | Rule evaluation engine — evaluates `rules.yaml` predicates against detector state |
| `rules.yaml` | Anomaly rule catalog — A-001 through A-010 with thresholds, suppression, severity |
| `migrate.py` | DB schema migration runner |

### Tests — Legacy / Sprint Acceptance

| File | Status | Notes |
|---|---|---|
| `test_sprint1.py` | Superseded | Sprint 1 acceptance tests against the flat gateway |
| `test_sprint2.py` | Superseded | Sprint 2 acceptance tests |
| `test_anomaly_rules.py` | Superseded | Rules engine tests (OPS-004) |
| `test_mqtt_bridge.py` | Superseded | MQTT bridge tests (flat version) |
| `test_scoring.py` | Superseded | Health scoring tests |
| `test_summaries.py` | Superseded | Fleet summary tests |
| `test_flow.sh` | Reference | Curl-based smoke test — still useful for manual QA against a live gateway |
| `__init__.py` | Remove | Artifact — root package init not needed |

### Internal Development Documents

These were board/planning documents committed to the repo root during active development. They are not end-user documentation.

| File | Description |
|---|---|
| `CNP-SPRINT-1_PATCH_NOTES.md` | Sprint 1 internal patch notes |
| `CNP-SPRINT-2_PATCH_NOTES.md` | Sprint 2 internal patch notes |
| `CNP-OPS-005_PATCH_NOTES.md` | OPS-004 patch notes |
| `cnp_board_003_engineering_board.md` | Engineering board — tickets, acceptance criteria |
| `cnp_exec_002_amended_execution_plan.docx.md` | Amended execution plan |

---

## SQL Migrations (moved to `db/migrations/`)

The `*.sql` files that were at the repository root have been relocated:

```
db/migrations/
├── 0001_baseline_schema.sql      (was: node_registry.sql)
├── 0002_v2_views_and_trim.sql    (was: 001_v2_views_and_trim.sql)
├── 0003_ops_tables.sql           (was: 002_ops_tables.sql)
├── 0004_v1_to_v2_schema.sql      (was: 003_v1_to_v2_schema.sql)
└── 0005_per_node_secrets.sql     (was: 004_per_node_secrets.sql)
```

The production gateway (`gateway/app/core/db.py:init_db()`) manages schema creation directly via `SCHEMA_SQL` — it does not run these migration files at startup. These files are reference materials for manual DB management and future migration tooling.

---

## Re-integrating the OPS-004 modules

If you want to wire `detector.py`, `scoring.py`, and `healer.py` into the production gateway:

1. Move them into `gateway/app/core/` and refactor imports
2. Inject `OpsDetector` into `GatewayMqttBridge` via the existing `set_ops_detector()` hook in `mqtt_client.py`
3. Add the ops tables from `db/migrations/0003_ops_tables.sql` to `db.py:SCHEMA_SQL`
4. Write tests in `gateway/tests/test_ops_detector.py`

The hook is already in place — `_handle_heartbeat()` calls `self._ops_detector.on_heartbeat(envelope)` if set.
