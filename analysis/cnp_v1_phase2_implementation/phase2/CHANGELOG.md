# Changelog

All notable changes to the CNP v1 Starter Kit are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Phase 2: Docker multi-stage build (`gateway/Dockerfile`)
- Phase 2: `docker-compose.yml` with gateway + Mosquitto services
- Phase 2: `pyproject.toml` replacing `requirements.txt` (PEP 517, hatchling)
- Phase 2: `CONTRIBUTING.md` with full development setup guide
- Phase 2: `SECURITY.md` with vulnerability disclosure policy
- Phase 2: `legacy/` directory with `ARCHIVED.md` explaining root-level flat files
- Phase 2: `db/migrations/` directory reorganising root-level SQL files
- Phase 2: Admin API reference in `docs/api/admin.md`

---

## [0.2.0] — 2026-03-18

### Summary
Major refactor from flat-file prototype to production-structured FastAPI application with security hardening, concurrent SQLite support, authenticated admin endpoints, MQTT rate limiting, and an automated test suite.

### Added
- `gateway/app/` — modular FastAPI application replacing root-level `gateway.py` monolith
  - `core/auth.py` — HMAC-SHA256 per-node secrets, provisioning, rotation
  - `core/db.py` — WAL mode SQLite with `db_connect()` helper (busy_timeout=5000ms)
  - `core/mqtt_client.py` — async MQTT bridge with per-client rate limiting and quarantine
  - `core/rate_limit.py` — three-tier sliding window (global / IP / node) with middleware
  - `core/registry.py` — node upsert, heartbeat update, offline detection
  - `core/storage.py` — event, error, ack, command CRUD
  - `api/routes.py` — main REST API with Pydantic v2 validation throughout
  - `api/admin.py` — fleet status, secret provisioning and rotation (authenticated)
  - `api/compat.py` — V1 backward-compatibility shim at `/v1/compat/node/*`
  - `models/schemas.py` — Envelope, NodeResponse, CommandRequest, MessageType enum
- `gateway/tests/` — pytest test suite (125 tests, 70%+ coverage)
  - `conftest.py` — in-memory SQLite fixtures, MockMqttBridge, helper factories
  - `test_api.py` — 11 contract and OpenAPI shape tests
  - `test_mqtt_handlers.py` — 30 MQTT handler unit tests (all 7 paths)
  - `test_p0_regressions.py` — 9 regression tests for CRITICAL audit findings
  - `test_p1_sql_and_config.py` — 22 SQL injection and config validation tests
- `firmware/` — PlatformIO ESP32-C3 project (modular header/source structure)
  - `Application.h/cpp` — main application loop
  - `ConfigManager.h/cpp` — NVS-backed config
  - `IdentityManager.h/cpp` — node identity
  - `TransportMqtt.h/cpp` — MQTT transport layer
  - `OtaManager.h/cpp` — OTA update support
  - `Protocol.h/cpp` — CNP v1 envelope builder
  - `EventQueue.h/cpp` — async event buffer
  - `modules_ExampleClimateModule.cpp` — reference module implementation
- `.github/workflows/ci.yml` — CI pipeline: ruff → mypy → bandit → pip-audit → pytest-cov → Docker build → repo hygiene
- `docs/DEPLOYMENT.md` — deployment guide
- `docs/TEST_FLOW.md` — test flow documentation
- `docs/schemas/` — CNP message and registry schema documentation
- `.env.example` — all required environment variables documented
- `LICENSE` — MIT license

### Changed
- **BREAKING (auth):** Admin endpoints now require `X-CNP-Admin-Token` header. Previously unauthenticated.
- **BREAKING (MQTT):** Subscription wildcard corrected from `cnp/v1/nodes/+/+` to `cnp/v1/nodes/+/#`. Multi-level topics (`cmd/out`) now received correctly.
- SQLite connections now use WAL journal mode — resolves 100% request timeout under concurrency
- `status` filter in `GET /api/nodes` now validated against allowlist `{online, offline, unknown, retired}`
- `priority` filter in `GET /api/events` now validated against allowlist `{low, normal, high, critical}`
- `PATCH /api/nodes/{id}/config` now validates `heartbeat_interval_sec` and `report_interval_sec` in range [10, 3600]
- Node API responses exclude `node_secret_hash` column (was exposed via `SELECT *`)
- `pytest-asyncio` dependency corrected from non-existent `==1.1.0` to `>=0.23,<1.0`
- All DB access paths use canonical `db_connect()` — WAL + busy_timeout applied consistently

### Fixed
- `GET /api/nodes` 100% ReadTimeout under concurrent load (SQLite locking — WAL fix)
- `pytest` exit code 4 (collection error) — invalid `pytest-asyncio` pin
- Admin endpoints accessible without authentication
- MQTT `cmd/out` messages silently dropped (wildcard bug)
- `X-Forwarded-For` trusted without proxy validation (IP spoofing vector)

### Deprecated
- Root-level `gateway.py` and all flat-file Python modules — see `legacy/ARCHIVED.md`

### Security
- Admin endpoints now authenticated with `ADMIN_TOKEN` / `X-CNP-Admin-Token`
- SQL injection vectors in `list_nodes()` and `list_events()` removed via allowlist validation
- Committed SQLite database files removed from repository history

---

## [0.1.0] — 2026-01-15

### Summary
Initial working prototype. Single flat-file gateway proving the CNP v1 protocol end-to-end with a single ESP32-C3 node over HTTP.

### Added
- `gateway.py` — flat FastAPI gateway with SQLite persistence
- `node_registry.sql` — initial database schema
- `cnp_node_skeleton.ino` — ESP32-C3 Arduino base firmware
- `cnp_v1_schemas.json` — JSON Schema definitions for all CNP message types
- `cnp_v1_unified_spec.md` — full protocol specification
- `test_flow.sh` — curl-based smoke test for the full node lifecycle
- `README.md` — quickstart and API reference

---

[Unreleased]: https://github.com/AvaPrime/cnp_v1_starter_kit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/AvaPrime/cnp_v1_starter_kit/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/AvaPrime/cnp_v1_starter_kit/releases/tag/v0.1.0
