# CNP-SPRINT-2 — EPIC-02 Implementation Patch Notes

**Covers:** CNP-BOARD-003 EPIC-02 · P2-01 through P2-08  
**Target:** Sprint 3 + Sprint 4 (Weeks 3–4)  
**Phase:** PHASE 2 — Secure Compatibility Layer  
**Prerequisite:** EPIC-01 Sprint 1 patch applied and green  

---

## Files in this patch

```
migrations/
  003_v1_to_v2_schema.sql      P2-04 — V1 → V2 DDL, all column changes
  004_per_node_secrets.sql     P2-02 — node_secret_hash column + rate log

gateway/app/
  api/compat.py                P2-03 + P2-05 — /v1/compat/* router
  api/admin.py                 P2-02 + P2-08 — provisioning + fleet endpoints
  core/auth.py                 P2-02 — HMAC secret logic

scripts/
  migrate.py                   P2-04 — CLI: --dry-run, --rollback, integrity check

docs/
  TLS_SETUP.md                 P2-01 — Mosquitto TLS + ESP32 WiFiClientSecure

gateway/tests/
  test_sprint2.py              P2-06 — 11-step compat lifecycle + field translation
                                        + provisioning tests + migration DDL tests
```

---

## Ticket mapping

| Ticket | File(s) | Key change |
|---|---|---|
| P2-01 | docs/TLS_SETUP.md | Complete TLS guide + firmware path code snippets |
| P2-02 | core/auth.py, migrations/004_per_node_secrets.sql, api/admin.py | HMAC provisioning, rotation, Stage 2 validate_node_token |
| P2-03 | api/compat.py | /v1/compat/* router, all 5+1 endpoints |
| P2-04 | migrations/003_v1_to_v2_schema.sql, scripts/migrate.py | Full DDL + CLI |
| P2-05 | api/compat.py (_translate_envelope) | All 9 V1→V2 field translations |
| P2-06 | tests/test_sprint2.py (TestCompatAdapter) | 11-step pytest lifecycle |
| P2-07 | api/compat.py (Depends(require_node_token)) | Same auth gate as V2 |
| P2-08 | api/admin.py | /api/fleet/status + /api/nodes/{id}/provision |

---

## Wire into main.py

Add to `gateway/app/main.py`:

```python
from .api.compat import router as compat_router
from .api.admin import router as admin_router

# In lifespan, after init_db + apply_migrations:
# (no changes needed — migrations run automatically)

# After app.include_router(router, prefix="/api"):
app.include_router(compat_router, prefix="/v1/compat")
app.include_router(admin_router, prefix="/api")
```

Full updated `lifespan` requires no further changes from Sprint 1.

---

## Apply migrations

Migrations run automatically on startup via `_apply_migrations()`.
Files are applied in sorted order: 001, 002 (ops), 003, 004.

Manual apply:
```bash
sqlite3 $GATEWAY_DB_PATH < migrations/003_v1_to_v2_schema.sql
sqlite3 $GATEWAY_DB_PATH < migrations/004_per_node_secrets.sql
```

V1 database migration (one-time, for existing deployments):
```bash
python scripts/migrate.py --source /path/to/codessa_registry.db --dry-run
python scripts/migrate.py --source /path/to/codessa_registry.db
```

---

## Update config.py for TLS support (P2-01)

```python
# gateway/app/core/config.py — add to Settings dataclass
mqtt_tls_enabled:  bool = os.getenv("MQTT_TLS_ENABLED", "false").lower() == "true"
mqtt_tls_ca_path:  str  = os.getenv("MQTT_TLS_CA_PATH", "")
mqtt_tls_cert_path: str = os.getenv("MQTT_TLS_CERT_PATH", "")
mqtt_tls_key_path:  str = os.getenv("MQTT_TLS_KEY_PATH", "")
```

See `docs/TLS_SETUP.md` for the full `_default_factory` update.

---

## Run tests

```bash
cd gateway
BOOTSTRAP_TOKEN=test-bootstrap-token-001 \
pytest tests/test_sprint2.py -v \
  --cov=app --cov-report=term-missing
```

Additional full suite:
```bash
BOOTSTRAP_TOKEN=test-bootstrap-token-001 \
pytest tests/ -v --cov=app --cov-fail-under=75
```

---

## Expected coverage after Sprint 2

| Module | Target | Key paths covered |
|---|---|---|
| `app/api/compat.py` | ≥ 80% | All 6 compat endpoints, field translations |
| `app/core/auth.py` | ≥ 85% | provision, rotate, validate (HMAC + bootstrap) |
| `app/api/admin.py` | ≥ 75% | fleet/status, provision, rotate-secret |
| Overall gateway | ≥ 75% | Phase 2 exit gate |

---

## Exit gate checklist (EPIC-02)

- [ ] **P2.1** `migrate.py --dry-run` on 10k-row V1 fixture: zero errors  
  `python scripts/migrate.py --source test_v1.db --dry-run`
- [ ] **P2.2** `TestCompatAdapter` 11-step test passes in CI  
  `pytest tests/test_sprint2.py::TestCompatAdapter -v`
- [ ] **P2.3** TLS broker test: `mosquitto_sub --cafile certs/ca.crt -p 8883 -t test` connects; plain `-p 1883` refused (manual step — document result in CI notes)
- [ ] **P2.4** Coverage ≥ 75%  
  `pytest --cov-fail-under=75`

---

## Notes on P2-02 two-stage auth upgrade

The `validate_bootstrap_token` function in `models/schemas.py` (Sprint 1)
is not replaced — it remains valid for nodes without per-node secrets.

The upgrade path:
1. Node registers via bootstrap token → `node_secret_hash = NULL`
2. Operator calls `POST /api/nodes/{id}/provision` → secret generated
3. Operator delivers secret to node via USB/QR
4. Node stores secret in NVS, computes HMAC token from it
5. All subsequent requests use HMAC token
6. Bootstrap token disabled per-zone via `BOOTSTRAP_DISABLED=true`

The `require_node_token` dependency in `routes.py` currently calls
`validate_bootstrap_token` (Stage 1). To upgrade to Stage 2, replace
with a call to `validate_node_token(db_path, node_id, token)` from `auth.py`.
The node_id must be extracted from the request body — this is a
Sprint 3+ change once per-node provisioning is rolled out to the fleet.

---

## Field translation deprecation window policy

Every V1 key accepted by `_translate_envelope()` emits:
```
DEPRECATION_V1_KEY original_key=<key> canonical_key=<key> node_id=<id>
```

These warnings are logged at WARNING level and queryable from ops logs.
V1 key support will be removed in CNP v1.5 (not this release cycle).

---

*CNP-SPRINT-2 · Codessa Systems · March 2026*
