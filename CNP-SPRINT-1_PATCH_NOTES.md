# CNP-SPRINT-1 — EPIC-01 Implementation Patch Notes

**Covers:** CNP-BOARD-003 EPIC-01 · P1-01 through P1-10  
**Target:** Sprint 1 + Sprint 2 exit gates  
**Phase:** PHASE 1 — Stabilise the Core  

---

## Files in this patch

```
migrations/
  001_v2_views_and_trim.sql     P1-08 + P1-09

gateway/app/
  main.py                       Updated — migration runner, rate limit middleware
  core/mqtt_client.py           P1-01 wildcard fix + P1-03 injectable factory
                                + P1-05 MQTT rate limiting
  core/rate_limit.py            P1-04 HTTP rate limiting middleware
  models/schemas.py             P1-02 NodeResponse + P1-06 Envelope validation
                                + P1-07 bootstrap token auth
  api/routes.py                 P1-02 DTO on all node routes + P1-06 envelope
                                + P1-07 auth dependency + P1-08 view-backed endpoints

gateway/tests/
  conftest.py                   P1-03 injectable bridge fixture + DB fixture
  test_sprint1.py               P1-10 — nodes, validation, rate limit, integration
  test_mqtt_bridge.py           P1-03 — handler dispatch, wildcard fix, rate limit
```

---

## Ticket mapping

| Ticket | File(s) | Key change |
|---|---|---|
| P1-01 | mqtt_client.py | `cnp/v1/nodes/+/#` replaces `cnp/v1/nodes/+/+` |
| P1-02 | models/schemas.py, api/routes.py | `NodeResponse` DTO, `from_row()` enforces exclusion |
| P1-03 | mqtt_client.py, tests/conftest.py | `client_factory` param, `InMemoryBroker` fixture |
| P1-04 | core/rate_limit.py, main.py | `RateLimitMiddleware`, 3-tier sliding windows |
| P1-05 | mqtt_client.py | `_ClientRateState`, per-sec + burst + quarantine |
| P1-06 | models/schemas.py, api/routes.py | `Envelope` Pydantic model, `_parse_envelope()` |
| P1-07 | models/schemas.py, api/routes.py | `BOOTSTRAP_TOKEN`, `require_node_token` dependency |
| P1-08 | migrations/001_v2_views_and_trim.sql | 5 views ported to V2 column names |
| P1-09 | migrations/001_v2_views_and_trim.sql | `trim_heartbeats` AFTER INSERT trigger |
| P1-10 | tests/conftest.py, test_sprint1.py, test_mqtt_bridge.py | Full test suite |

---

## Prerequisites

```
BOOTSTRAP_TOKEN=<your-secret>   # required — gateway refuses to start without it
```

Add to `gateway/requirements.txt` (fix P1-10 pytest-asyncio version):
```
pytest-asyncio>=0.23
httpx>=0.28
```

---

## Apply migration

```bash
cd gateway
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
# Migration runs automatically on startup via _apply_migrations()
```

Or manually:
```bash
sqlite3 $GATEWAY_DB_PATH < ../migrations/001_v2_views_and_trim.sql
```

---

## Run tests

```bash
cd gateway
BOOTSTRAP_TOKEN=test-bootstrap-token-001 \
pytest tests/test_sprint1.py tests/test_mqtt_bridge.py \
  -v --cov=app --cov-report=term-missing
```

### Expected coverage after Sprint 1+2

| Module | Target | Notes |
|---|---|---|
| `app/api/routes.py` | ≥ 70% | Integration tests cover all routes |
| `app/core/mqtt_client.py` | ≥ 75% | Bridge unit tests cover all handlers |
| `app/core/rate_limit.py` | ≥ 80% | Rate limit tests cover all tiers |
| `app/models/schemas.py` | ≥ 85% | 12 invalid + valid fixture tests |
| Overall gateway | ≥ 60% | Phase 1 exit gate |

---

## Exit gate checklist (EPIC-01)

- [ ] **P1.1** `pytest tests/test_mqtt_bridge.py` passes — bridge starts and dispatches without broker
- [ ] **P1.2** `pytest tests/test_sprint1.py::TestRateLimiting` — throttle at 60/min, second client unaffected, breach events logged  
- [ ] **P1.3** `GET /api/nodes` response contains zero auth/secret fields — `test_node_response_excludes_secret_fields` passes
- [ ] **P1.4** 12 invalid envelope fixtures all return 422, none written to DB — `TestValidation` passes
- [ ] **P1.5** Coverage ≥ 60% — `pytest --cov-fail-under=60` green

---

## What's NOT in this patch (deferred to Sprint 3+)

- P2-01 TLS broker documentation
- P2-02 per-node secret provisioning
- P2-03 V1 compat adapter (`/v1/compat/*` router)
- P2-04 V1 → V2 DB migration DDL
- `node_config` table (present in V1 schema, referenced in routes — ensure 001 migration adds if missing)

---

## One known gap to fix before running tests

The `node_config` table is referenced in `node_hello` but is only present
in the V1 `node_registry.sql` schema, not the V2 `SCHEMA_SQL` in `db.py`.
Add it to `gateway/app/core/db.py` `SCHEMA_SQL`:

```sql
CREATE TABLE IF NOT EXISTS node_config (
    node_id                TEXT PRIMARY KEY REFERENCES nodes(node_id),
    heartbeat_interval_sec INTEGER NOT NULL DEFAULT 60,
    report_interval_sec    INTEGER NOT NULL DEFAULT 60,
    permissions_json       TEXT,
    custom_json            TEXT,
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
```

---

*CNP-SPRINT-1 · Codessa Systems · March 2026*
