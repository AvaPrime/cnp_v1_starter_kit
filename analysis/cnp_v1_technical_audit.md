**CODESSA NODE PROTOCOL v1**

cnp\_v1\_starter\_kit

**TECHNICAL AUDIT & PRODUCTION READINESS ROADMAP**

Prepared for: Phoenix / Codessa OS / Ava Prime

Audit Date: 18 March 2026   |   Auditor: Claude (Ava Prime Co-Architect)

**Classification: INTERNAL — Not for Public Distribution Until Roadmap Complete**

# **1\. Executive Summary**

CNP v1 (Codessa Node Protocol) is a well-conceived IoT gateway protocol built on FastAPI, aiosqlite, and MQTT targeting ESP32-C3 edge nodes. The structured codebase inside gateway/app/ demonstrates solid architectural intent — clean separation of concerns, Pydantic v2 validation, HMAC-based per-node auth, and a compat layer for backward compatibility. However, the repository has a set of critical blockers that prevent both safe production operation and responsible public GitHub release.

The audit identified 4 CRITICAL findings, 6 HIGH-severity findings, and 8 MEDIUM/LOW findings across 10 audit dimensions. The most dangerous: admin endpoints (secret provisioning, rotation) are completely unauthenticated; SQLite connection handling causes 100% request failure under any concurrent load; the test suite never ran due to an invalid dependency pin; and the repository contains no license, no .gitignore, and committed database files.

The production readiness roadmap is structured into 4 phases across \~10 weeks, delivering a secure, tested, documented, CI/CD-gated public release at Phase 4 completion.

## **Audit Scorecard**

| Dimension | Score | Critical Findings | Status |
| :---- | :---- | :---- | :---- |
| Code Quality & Architecture | **6 / 10** | Root-level file chaos, no pyproject.toml | Needs Refactor |
| Security | **3 / 10** | Admin endpoints unauthenticated, DB committed | Blocker |
| Performance | **2 / 10** | 100% timeout on /api/nodes under load | Blocker |
| Dependency Management | **4 / 10** | Invalid pytest-asyncio pin, no lock file | Blocker |
| Testing Coverage | **3 / 10** | Tests never ran (exit code 4\) | Blocker |
| Documentation | **5 / 10** | Missing CONTRIBUTING, SECURITY, CHANGELOG | Needs Work |
| CI/CD Pipeline | **0 / 10** | Zero CI/CD — no workflows, no Docker | Blocker |
| Repo Structure & Hygiene | **2 / 10** | No .gitignore, .db files committed | Blocker |
| Licensing Compliance | **0 / 10** | No LICENSE file — cannot publish | Blocker |
| Firmware / Embedded | **6 / 10** | Missing OTA verification, hardcoded URLs | Acceptable |

# **2\. Detailed Audit Findings**

## **2.1  Security**

**CRITICAL**  Admin endpoints have zero authentication

gateway/app/api/admin.py exposes three endpoints — /api/fleet/status, /api/nodes/{id}/provision, and /api/nodes/{id}/rotate-secret — with no Depends(require\_node\_token) or any auth guard. The /provision and /rotate-secret endpoints return plaintext node secrets. Any unauthenticated caller on the network can retrieve or rotate node credentials.

* **\[admin.py\]** fleet\_status, provision\_secret, rotate\_secret — none have an auth dependency

* **\[admin.py:ProvisionResponse\]** Plaintext secret is returned in the HTTP response body — one unauthenticated request exposes all node auth

**HIGH**  f-string SQL injection pattern in list\_nodes and list\_events

routes.py lines 129 and 218 build WHERE clauses via Python f-strings (f'SELECT \* FROM nodes {clause} ORDER BY node\_id LIMIT ?'). While the filter values are parameterized, the clause variable itself is constructed from user-controlled Query parameters without allowlist validation. This is a SQL injection vector if clause construction logic changes.

* **\[MEDIUM\]** routes.py:129 — f-string WHERE clause in list\_nodes

* **\[MEDIUM\]** routes.py:218 — f-string WHERE clause in list\_events

**HIGH**  X-Forwarded-For header trusted without validation — IP spoofing in rate limiter

rate\_limit.py:\_client\_ip() reads X-Forwarded-For without validating that the request came through a trusted proxy. An attacker can spoof IPs to bypass the per-IP rate limit by rotating X-Forwarded-For values.

**MEDIUM**  Two SQLite database files committed to the repository

codessa\_registry.db and gateway/cnp\_gateway.db are tracked in git. These may contain node identifiers, device UIDs, secrets hashes, or telemetry from local testing. They also bloat the repo and will appear in every clone.

**MEDIUM**  Rate limiter state is process-local — bypassed at any scale \>1 worker

All three sliding-window rate limiters (\_node\_limiter, \_ip\_limiter, \_global\_limiter) are Python module-level singletons. Each uvicorn worker has its own copy. In production with 4 workers, each node gets 4x the intended rate budget. There is no Redis or shared backend.

## **2.2  Performance**

**CRITICAL**  /api/nodes shows 100% ReadTimeout failure rate under any concurrent load

The benchmark data in analysis/out/performance\_summary.csv confirms: at concurrency=10 for 10 seconds, /api/nodes returned 0 successful responses on both the legacy files system and the production gateway — 10/10 ReadTimeout errors. /api/health shows 44–47% timeout rates at concurrency=25.

| Endpoint | Concurrency | Requests | OK | Errors | Error Type | RPS |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| /api/health | 25 | 107 | 57 | 50 | ReadTimeout | 9.3 |
| /api/nodes | 10 | 10 | 0 | 10 | ReadTimeout (100%) | 0.6 |
| /api/health (legacy) | 25 | 112 | 62 | 50 | ReadTimeout | 9.9 |
| /api/nodes (legacy) | 10 | 10 | 0 | 10 | ReadTimeout (100%) | 0.6 |

**CRITICAL**  No SQLite WAL mode or busy\_timeout in production gateway

gateway/app/core/db.py performs all writes in default journal mode (DELETE). Under concurrent reads and writes, SQLite uses exclusive write locks causing indefinite blocking. The legacy gateway.py correctly applies PRAGMA journal\_mode=WAL but the production gateway/app/ codebase does not. With aiosqlite opening a new connection per request (no pooling), write contention compounds into the observed timeout cascade.

* **Missing** No PRAGMA journal\_mode=WAL in db.py init\_db()

* **Missing** No PRAGMA busy\_timeout — locks block indefinitely

* **Missing** No connection pool — every route handler opens/closes a new connection

**MEDIUM**  SELECT \* queries expose internal schema and over-fetch

All node queries use SELECT \* — including columns like node\_secret\_hash that should never be returned to API consumers. NodeResponse.from\_row() filters at Python level but the hash still travels over the internal bus.

## **2.3  Code Quality & Architecture**

**HIGH**  20+ Python files dumped at repository root — dual codebase confusion

The root contains a complete parallel Python system: admin.py, api.py, auth.py, compat.py, db.py, detector.py, gateway.py (579 lines), healer.py, migrate.py, models.py, mqtt\_client.py, rate\_limit.py, routes.py, rules.py, schemas.py, scoring.py, summaries.py, plus six test files. These appear to be the legacy flat-file v1 system never cleaned up after the gateway/ refactor. Anyone cloning the repo is faced with two competing implementations with no clear entry point.

* **\[LEGACY\]** gateway.py (root) — 579-line monolith, includes WAL pragma that is missing from gateway/app/

* **\[PRODUCTION\]** gateway/ — clean modular FastAPI app, correct entry point

* **\[CONFUSION RISK\]** No README note or deprecation marker explaining the dual structure

**MEDIUM**  Rate limiter double-dipping — node check fires in middleware AND route handler

RateLimitMiddleware in middleware fires first for all /api/node/\* paths. Then node\_hello() and compat\_hello() also call check\_node\_rate() explicitly in the route body, consuming two slots per hello request from the node's per-60s budget.

**MEDIUM**  update\_node\_config accepts arbitrary body without Pydantic validation

routes.py:/api/nodes/{node\_id}/config PATCH reads body \= await request.json() without any schema validation. An attacker or buggy client can send arbitrary keys; the handler silently ignores unknown fields but heartbeat\_interval\_sec and report\_interval\_sec accept any value including negative numbers.

## **2.4  Testing Coverage**

**CRITICAL**  Test suite never ran — pytest-asyncio==1.1.0 does not exist

gateway/requirements.txt pins pytest-asyncio==1.1.0, which has never been published to PyPI. quality\_reports.json confirms pytest\_exit\_code: 4 (collection error — no tests collected, no tests ran). The coverage baseline is 0%.

| Test File | Location | Status | Scope |
| :---- | :---- | :---- | :---- |
| test\_api.py | gateway/tests/ | **NEVER RAN** | 11 contract/shape tests |
| test\_sprint1.py | root | Unknown (legacy) | Sprint 1 acceptance |
| test\_sprint2.py | root | Unknown (legacy) | Sprint 2 acceptance |
| test\_anomaly\_rules.py | root | Unknown (legacy) | Anomaly rules engine |
| test\_mqtt\_bridge.py | root | Unknown (legacy) | MQTT bridge |
| test\_scoring.py | root | Unknown (legacy) | Scoring system |
| test\_summaries.py | root | Unknown (legacy) | Summaries module |

The 11 tests in test\_api.py are high-quality contract tests (node\_id validation, error shape, OpenAPI schema assertions) and demonstrate good test design. The conftest.py is well-engineered: in-memory SQLite, MockMqttBridge injection, proper async fixtures. The foundation is solid — the only blocker is the invalid dependency.

**HIGH**  No MQTT handler unit tests, no integration tests, no firmware tests

MQTT ingestion (hello/heartbeat/event/error/ack/command\_result handlers in mqtt\_client.py) has zero test coverage. The MockMqttBridge exists but is not used in any handler-level test. The injectable client\_factory pattern (P1-03) is implemented but no test exercises it.

## **2.5  Dependency Management**

**CRITICAL**  pytest-asyncio==1.1.0 is a non-existent package version

Fix: replace with pytest-asyncio\>=0.23,\<1.0. This is a one-line change that unblocks the entire test suite.

**MEDIUM**  No dependency lock file — builds are not reproducible

requirements.txt pins exact versions for runtime deps but there is no poetry.lock, uv.lock, or pip-compile .txt that pins the full transitive closure. A fresh install may pull different transitive versions across environments.

| Package | Pinned Version | Latest (March 2026\) | Notes |
| :---- | :---- | :---- | :---- |
| fastapi | 0.116.1 | \~0.116.x | OK |
| uvicorn\[standard\] | 0.35.0 | \~0.35.x | OK |
| pydantic | 2.11.7 | \~2.11.x | OK |
| aiosqlite | 0.21.0 | \~0.21.x | OK |
| asyncio-mqtt | 0.16.2 | Deprecated — use aiomqtt | Consider migration |
| pytest-asyncio | 1.1.0 | 0.23.x / 0.24.x | DOES NOT EXIST — Fix immediately |
| orjson | 3.11.1 | \~3.11.x | OK |
| httpx | 0.28.1 | \~0.28.x | OK |

## **2.6  Repository Structure & Hygiene**

**CRITICAL**  No .gitignore — database files, \_\_pycache\_\_, .coverage are tracked

Both codessa\_registry.db and gateway/cnp\_gateway.db are committed and appear in the public repository tree. Without a .gitignore, every Python developer's \_\_pycache\_\_, .coverage, .env, and test artifacts will also be committed on next push.

**HIGH**  No Dockerfile, no docker-compose.yml, no .env.example

There is no containerization layer. The gateway requires BOOTSTRAP\_TOKEN, MQTT\_BROKER\_HOST, MQTT\_BROKER\_PORT, GATEWAY\_DB\_PATH, and CNP\_OFFLINE\_AFTER\_SECONDS — but there is no .env.example documenting these. A new contributor has no way to know what env vars to set.

**CRITICAL**  No LICENSE file — repository cannot legally be made public

Without a LICENSE file, all source code is implicitly All Rights Reserved under copyright law. GitHub's public repository default does not grant any rights to contributors or users. The repository cannot be published as open-source without choosing and adding a license.

**MEDIUM**  Sprint/patch notes and analysis artifacts at root — not documentation

CNP-SPRINT-1\_PATCH\_NOTES.md, CNP-SPRINT-2\_PATCH\_NOTES.md, CNP-OPS-004\_operational\_intelligence\_layer.md, cnp\_board\_003\_engineering\_board.md, cnp\_exec\_002\_amended\_execution\_plan.docx.md, and the full analysis/out/ directory (including server logs and performance CSVs) are committed at root. These are internal development artifacts, not end-user documentation.

## **2.7  CI/CD Pipeline**

**CRITICAL**  Zero CI/CD — no GitHub Actions workflows exist

There is no .github/ directory. No automated testing, linting, security scanning, build validation, Docker image building, or release automation runs on any push or PR. The codebase has no quality gate.

## **2.8  Documentation Completeness**

| Document | Exists? | Quality | Gap |
| :---- | :---- | :---- | :---- |
| README.md | YES | **GOOD** | Architecture diagram present, needs update for gateway/ structure |
| TLS\_SETUP.md | YES | **GOOD** | Covers TLS for MQTT |
| docs/DEPLOYMENT.md | YES | **FAIR** | Needs Docker, env var reference |
| docs/TEST\_FLOW.md | YES | **FAIR** | curl-based only, no pytest workflow |
| docs/schemas/ | YES | **GOOD** | Message and registry schemas documented |
| CONTRIBUTING.md | MISSING | **MISSING** | No contribution guidelines |
| SECURITY.md | MISSING | **MISSING** | No vulnerability disclosure process |
| CHANGELOG.md | MISSING | **MISSING** | No version history |
| .env.example | MISSING | **MISSING** | No env var documentation |
| API Reference (admin) | MISSING | **MISSING** | Admin endpoints entirely undocumented |

# **3\. Production Readiness Roadmap**

The roadmap is structured into 4 sequential phases. Phases 1–2 address blockers and must complete before any public release. Phases 3–4 deliver the hardened, observable, contributor-ready public repository.

## **Phase 0 — Pre-Sprint Blockers (Days 1–3)**

**GOAL**  Unblock testing and eliminate the most dangerous security hole

| ID | Action | File(s) | Effort | Priority |
| :---- | :---- | :---- | :---- | :---- |
| P0-01 | Fix pytest-asyncio pin: pytest-asyncio==1.1.0 → \>=0.23,\<1.0 | gateway/requirements.txt | 5 min | **CRITICAL** |
| P0-02 | Add pytest.ini with asyncio\_mode=auto, testpaths=tests, cov-fail-under=60 | gateway/pytest.ini | 15 min | **CRITICAL** |
| P0-03 | Add PRAGMA journal\_mode=WAL \+ busy\_timeout=5000 to init\_db() | gateway/app/core/db.py | 30 min | **CRITICAL** |
| P0-04 | Add async db\_connect() helper that sets pragmas \+ row\_factory on every connection | gateway/app/core/db.py | 1 hr | **CRITICAL** |
| P0-05 | Add X-CNP-Admin-Token auth dependency to ALL three admin endpoints | gateway/app/api/admin.py | 1 hr | **CRITICAL** |
| P0-06 | Create .gitignore covering \*.db, \_\_pycache\_\_, .venv, .coverage, .env, dist/ | /.gitignore | 15 min | **HIGH** |
| P0-07 | Remove committed DB files from git history (git filter-repo or BFG) | codessa\_registry.db, gateway/cnp\_gateway.db | 1 hr | **HIGH** |
| P0-08 | Add LICENSE file (recommend MIT or Apache 2.0) | /LICENSE | 10 min | **CRITICAL** |

### **P0-03/04 — SQLite WAL Implementation**

Add to gateway/app/core/db.py:

async def db\_connect(path: str) \-\> aiosqlite.Connection:

    db \= await aiosqlite.connect(path)  
    await db.execute("PRAGMA journal\_mode=WAL")  
    await db.execute("PRAGMA busy\_timeout=5000")

    db.row\_factory \= aiosqlite.Row

    return db

Replace all aiosqlite.connect(settings.gateway\_db\_path) call sites across routes.py, registry.py, storage.py, admin.py, and auth.py with async with db\_connect(path) as db.

### **P0-05 — Admin Auth Fix**

Add an admin token to Settings and create a require\_admin\_token dependency mirroring require\_node\_token. The ADMIN\_TOKEN must be a separate secret from BOOTSTRAP\_TOKEN — add both to .env.example.

## **Phase 1 — Security Hardening & Test Coverage (Days 4–14)**

**GOAL**  Reach 60% test coverage, fix all security findings, enable CI

| ID | Action | Priority | Effort (days) |
| :---- | :---- | :---- | :---- |
| P1-01 | Refactor SQL clause building — replace f-string WHERE with allowlist pattern in list\_nodes() and list\_events() | **HIGH** | 0.5 |
| P1-02 | Add Pydantic schema for PATCH /nodes/{id}/config — validate heartbeat\_interval\_sec range \[10, 3600\] | **HIGH** | 0.5 |
| P1-03 | Fix MQTT wildcard: cnp/v1/nodes/+/+ → cnp/v1/nodes/+/\# (bug confirmed in state review) | **HIGH** | 0.5 |
| P1-04 | Add X-Forwarded-For trusted proxy allowlist — env var TRUSTED\_PROXIES in Settings | **MEDIUM** | 0.5 |
| P1-05 | Eliminate rate limiter double-dip: remove explicit check\_node\_rate() calls in routes/compat, rely on middleware only | **MEDIUM** | 0.5 |
| P1-06 | Replace SELECT \* with explicit column lists across all query sites; add node\_secret\_hash to column blocklist | **MEDIUM** | 1 |
| P1-07 | Write MQTT handler unit tests using injectable client\_factory mock — hello, heartbeat, event, error, ack, cmd\_result | **HIGH** | 2 |
| P1-08 | Write integration test: full node lifecycle (hello → heartbeat → event → command → ack) against in-memory SQLite | **HIGH** | 1 |
| P1-09 | Write concurrency regression test: 20 parallel /api/nodes requests — assert all return 200 within 1s | **CRITICAL** | 0.5 |
| P1-10 | Create GitHub Actions workflow: ci.yml — lint (ruff), type-check (mypy), test (pytest \--cov), bandit scan | **CRITICAL** | 1 |

### **P1-10 — GitHub Actions CI Spec**

| Step | Tool | Threshold / Gate |
| :---- | :---- | :---- |
| Lint | ruff check . \--select E,F,W,I | Exit 0 required |
| Type Check | mypy gateway/app \--strict | Exit 0 required (can start permissive) |
| Security Scan | bandit \-r gateway/app \-ll | SEVERITY.HIGH \= 0 |
| Test \+ Coverage | pytest \--cov=app \--cov-fail-under=60 | Coverage \>= 60% |
| Dependency Audit | pip-audit \-r gateway/requirements.txt | 0 known CVEs |
| Build Docker Image | docker build \-t cnp-gateway:test . | Build must succeed |

## **Phase 2 — Repository Cleanup & Documentation (Days 15–21)**

**GOAL**  Clean public-facing repo, complete contributor docs, Docker packaging

| ID | Action | Effort (days) |
| :---- | :---- | :---- |
| P2-01 | Archive root-level legacy Python files into legacy/ subdirectory with ARCHIVED.md explaining deprecation | 0.5 |
| P2-02 | Restructure repo: move conftest.py to gateway/tests/, migrate SQL files to db/migrations/ | 0.5 |
| P2-03 | Remove analysis/out/ from git tracking (add to .gitignore) — move to docs/internal/ if needed | 0.5 |
| P2-04 | Create Dockerfile for gateway service with multi-stage build (builder \+ slim runtime) | 1 |
| P2-05 | Create docker-compose.yml with gateway \+ mosquitto MQTT broker services | 0.5 |
| P2-06 | Create .env.example documenting all env vars: BOOTSTRAP\_TOKEN, ADMIN\_TOKEN, MQTT\_\*, GATEWAY\_DB\_PATH, CNP\_OFFLINE\_AFTER\_SECONDS | 0.5 |
| P2-07 | Write CONTRIBUTING.md: development setup, PR process, commit conventions, test requirements | 0.5 |
| P2-08 | Write SECURITY.md: vulnerability disclosure policy, contact, response SLA | 0.5 |
| P2-09 | Create CHANGELOG.md: document v0.1.0 (flat), v0.2.0 (modular gateway), planned v1.0.0 | 0.5 |
| P2-10 | Migrate to pyproject.toml (PEP 517): replace requirements.txt, add \[project.optional-dependencies\] for dev | 1 |
| P2-11 | Update README.md: correct architecture diagram, docker-compose quickstart, env var reference, contributor guide link | 0.5 |
| P2-12 | Add API reference section to docs/ for admin endpoints (provision, rotate, fleet-status) | 0.5 |

### **Target Repo Structure After Phase 2**

cnp\_v1\_starter\_kit/

├── gateway/            \# Production FastAPI gateway

│   ├── app/

│   │   ├── api/        \# routes, compat, admin

│   │   ├── core/       \# auth, config, db, mqtt, registry, storage

│   │   └── models/     \# schemas

│   ├── tests/          \# All tests \+ conftest.py

│   └── pyproject.toml

├── firmware/           \# PlatformIO ESP32-C3 project

├── db/migrations/      \# \*.sql migration files

├── docs/               \# DEPLOYMENT, TEST\_FLOW, schemas, API reference

├── legacy/             \# Archived root-level flat files (ARCHIVED.md)

├── examples/           \# Config examples

├── .github/workflows/  \# ci.yml, release.yml

├── .env.example

├── .gitignore

├── CHANGELOG.md

├── CONTRIBUTING.md

├── LICENSE

├── README.md

└── SECURITY.md

## **Phase 3 — Performance Optimization & Observability (Days 22–35)**

**GOAL**  Eliminate all timeout failures, add structured logging, metrics, health-check depth

| ID | Action | Expected Impact |
| :---- | :---- | :---- |
| P3-01 | Implement aiosqlite connection pool using asyncio.Queue (pool\_size=5, max\_overflow=10) | Eliminate connection-per-request overhead — expected to resolve /api/nodes timeouts |
| P3-02 | Add DB index: CREATE INDEX IF NOT EXISTS idx\_events\_priority\_ts ON events(priority, ts\_utc DESC) | 10x speedup on /api/alerts with large event tables |
| P3-03 | Add DB index: CREATE INDEX IF NOT EXISTS idx\_commands\_node\_status ON commands(node\_id, status) | Fast pending command lookup per node |
| P3-04 | Migrate rate limiter to Redis (use redis-py async) — add REDIS\_URL to Settings with fallback to in-memory for dev | Rate limiting works across multiple uvicorn workers |
| P3-05 | Add structured JSON logging with structlog — include node\_id, trace\_id, latency\_ms on every request | Enables log aggregation and alerting |
| P3-06 | Add Prometheus metrics endpoint /metrics using prometheus-fastapi-instrumentator | CPU, memory, request latency, error rates observable |
| P3-07 | Deepen /api/health: add MQTT broker reachability check, SQLite write test, version metadata | Enables load balancer health gate and uptime monitoring |
| P3-08 | Add async timeout wrapper (asyncio.wait\_for) on all DB operations — 3s max per query | Prevents indefinite hang; returns 503 instead of client ReadTimeout |
| P3-09 | Add pagination cursor to /api/events and /api/nodes (cursor-based, not OFFSET) | Prevents full table scan on large fleets |

## **Phase 4 — Public Release & Release Management (Days 36–42)**

**GOAL**  Publish v1.0.0 to GitHub with full release automation, community readiness

| ID | Action | Effort |
| :---- | :---- | :---- |
| P4-01 | Create GitHub release workflow (release.yml): tag → build Docker → push to GHCR → create GitHub release with CHANGELOG entry | 1 day |
| P4-02 | Publish container image: ghcr.io/avaprime/cnp-gateway:1.0.0 with multi-arch build (linux/amd64, linux/arm64) | 0.5 day |
| P4-03 | Add CODEOWNERS file: assign gateway/ and firmware/ ownership | 0.5 hr |
| P4-04 | Add GitHub issue templates: bug\_report.yml, feature\_request.yml, security\_advisory.yml | 1 hr |
| P4-05 | Add pull\_request\_template.md with checklist: tests pass, coverage maintained, docs updated | 1 hr |
| P4-06 | Add dependabot.yml: automated dependency updates for pip and GitHub Actions | 30 min |
| P4-07 | Final pre-release audit: run bandit, pip-audit, check no .db files, verify LICENSE present | 2 hr |
| P4-08 | Tag v1.0.0 — trigger release workflow | 30 min |

# **4\. Milestones, Success Metrics & Quality Gates**

| Milestone | Target Day | Quality Gate (must pass before proceeding) | Success Metric |
| :---- | :---- | :---- | :---- |
| M0: Blockers Cleared | Day 3 | pytest exits 0; /api/nodes returns 200 at concurrency=10; admin endpoints require token | Test suite green; 0% timeout on nodes endpoint |
| M1: Security Green | Day 14 | bandit SEVERITY.HIGH=0; all admin routes return 401 without token; coverage ≥ 60% | CI pipeline green on every PR |
| M2: Repo Clean | Day 21 | No \*.db in git history; .gitignore committed; LICENSE present; Docker build succeeds | Docker image builds and gateway starts in \<10s |
| M3: Observable | Day 35 | /api/health reflects real broker \+ DB state; /metrics endpoint live; 0% timeout at concurrency=25 | p99 latency \< 200ms at 25 concurrent clients |
| M4: Public Release | Day 42 | All quality gates pass; CHANGELOG entry for v1.0.0; GHCR image published; GitHub release created | First external contributor can set up in \<10 minutes using README \+ docker-compose |

## **Test Coverage Targets by Phase**

| Phase | Coverage Floor | New Test Areas |
| :---- | :---- | :---- |
| Phase 0 (M0) | ≥ 30% | Existing 11 tests run for first time |
| Phase 1 (M1) | ≥ 60% | MQTT handlers, lifecycle integration, concurrency regression |
| Phase 2 (M2) | ≥ 70% | Admin auth, config validation, compat layer |
| Phase 3 (M3) | ≥ 80% | Connection pool, rate limiter, pagination, health endpoint |
| Phase 4 (M4) | ≥ 85% | Error paths, OTA handler, firmware MQTT topics |

# **5\. GitHub Public Release Strategy**

## **5.1  Pre-Release Checklist**

| Category | Item | Status |
| :---- | :---- | :---- |
| Legal | LICENSE file present (MIT recommended for IoT starter kit) | **NOT DONE** |
| Legal | All contributed code is from original authors (no copy-pasted proprietary code) | **VERIFY** |
| Security | No secrets, passwords, or tokens in git history | **NOT DONE** |
| Security | No database files in repository | **NOT DONE** |
| Security | SECURITY.md with vulnerability disclosure policy | **NOT DONE** |
| Quality | CI passes on main branch | **NOT DONE** |
| Quality | Test coverage ≥ 60% | **NOT DONE** |
| Community | CONTRIBUTING.md with setup instructions | **NOT DONE** |
| Community | Issue templates and PR template | **NOT DONE** |
| Community | README docker-compose quickstart verified working | **NOT DONE** |
| Releases | CHANGELOG.md with v1.0.0 entry | **NOT DONE** |
| Releases | GitHub Release with release notes | **NOT DONE** |

## **5.2  Repository Topics & Visibility**

Recommended GitHub repository topics for discoverability: iot, mqtt, esp32, fastapi, sqlite, arduino, protocol, node-protocol, edge-computing, home-automation, codessa

## **5.3  Recommended License: MIT**

MIT is the best choice for an IoT starter kit intended to maximize adoption:

* Maximum adoption — commercial and hobbyist builders can embed without legal friction

* Compatible with ArduinoJson (MIT) and PubSubClient (MIT) — no license conflicts in firmware

* FastAPI (MIT) and uvicorn (BSD) are permissively licensed — full stack is MIT-compatible

* If you want attribution requirements for commercial use, consider Apache 2.0 instead

# **6\. Quick Wins (Execute in First 24 Hours)**

These 8 changes require \< 30 minutes total and eliminate the most dangerous findings immediately:

| \# | Action | Time | Impact |
| :---- | :---- | :---- | :---- |
| 1 | Fix gateway/requirements.txt: pytest-asyncio==1.1.0 → \>=0.23,\<1.0 | 2 min | **CRITICAL — tests can run** |
| 2 | Create gateway/pytest.ini with asyncio\_mode=auto and testpaths=tests | 5 min | **CRITICAL — CI unblocked** |
| 3 | Add Depends(require\_admin\_token) to all three admin endpoints in admin.py | 15 min | **CRITICAL — security hole closed** |
| 4 | Add PRAGMA journal\_mode=WAL \+ busy\_timeout=5000 to init\_db() in db.py | 10 min | **CRITICAL — resolves /api/nodes timeouts** |
| 5 | Create .gitignore: \*.db, \_\_pycache\_\_, .venv, .env, .coverage, dist/, build/ | 5 min | **HIGH — prevents future DB commits** |
| 6 | Add LICENSE file (MIT — copy from choosealicense.com/licenses/mit) | 2 min | **CRITICAL — enables public release** |
| 7 | Create .env.example documenting BOOTSTRAP\_TOKEN, ADMIN\_TOKEN, MQTT\_\* vars | 10 min | **HIGH — contributor onboarding** |
| 8 | Fix MQTT wildcard: cnp/v1/nodes/+/+ → cnp/v1/nodes/+/\# | 2 min | **HIGH — MQTT cmd/out topics now received** |

# **7\. Firmware Audit Notes**

| Finding | Severity | Recommendation |
| :---- | :---- | :---- |
| WiFi credentials hardcoded in \#define constants at top of sketch | **HIGH** | Use NVS (Preferences library) for credentials storage; never in source |
| GATEWAY\_URL hardcoded — no mDNS or discovery mechanism | **MEDIUM** | Add mDNS discovery or provision via BLE/captive portal on first boot |
| OTA update downloads without signature verification | **HIGH** | Add ECDSA or RSA-PSS signature check on OTA payload before flashing |
| No TLS on HTTP transport — tokens transmitted in plaintext | **HIGH** | Enforce TLS\_SETUP.md for production; add cert bundle to firmware |
| ArduinoJson 7.0.4 pinned — no automated update path | **LOW** | Consider dependabot for lib\_deps or lock to patch version |
| NODE\_TOKEN hardcoded in \#define — cannot rotate without reflash | **HIGH** | Implement per-node secrets via NVS with over-the-air token rotation support |

# **8\. Strategic Notes for Ava Prime Integration**

## **8.1  Memory Cortex Bridge Hook**

gateway/app/api/routes.py:node\_event() contains the labeled MEMORY BRIDGE HOOK comment. This is the correct integration point. Recommended pattern:

* Post-insert, fire-and-forget asyncio.create\_task(forward\_to\_memory\_cortex(node\_id, envelope)) — do not block the route response

* Add circuit breaker: if memory cortex is down, buffer events in a separate SQLite queue table and retry

* The envelope's message\_id makes events idempotent — safe for at-least-once delivery to Supabase/ChromaDB

## **8.2  Multi-Agent Orchestration Surface**

The existing admin API endpoints (provision, rotate, fleet-status) plus the rules engine (rules.py, rules.yaml at root) form the natural Ava Prime agent control surface. Recommended evolution:

* Expose /api/fleet/status and /api/summary as Ava Prime MCP tool endpoints

* Wire rules.yaml triggers to Ava Prime decision agents — replace the flat rules engine with LangGraph node

* Add a /api/agent/command endpoint that wraps create\_command() with agent identity tracking (issued\_by field)

## **8.3  Phase 6 MQTT vs. Conversation Graph OS**

The roadmap's Phase 6 target (HTTP → MQTT transport) aligns directly with the Conversation Graph OS memory substrate pattern. MQTT topic hierarchy cnp/v1/nodes/{node\_id}/{type} maps cleanly to a graph edge model. Consider treating each node's topic stream as a conversation thread in the graph — enabling temporal replay and pattern detection across the fleet.

# **Appendix — Bandit Security Scan Summary**

Bandit was run on the analysis/run\_comparative\_analysis.py and the legacy gateway.py. The production gateway/app/ was NOT scanned in the pre-existing quality\_reports.json — this must be added to the CI pipeline as P1-10.

| File | Severity | Confidence | Finding | CWE |
| :---- | :---- | :---- | :---- | :---- |
| run\_comparative\_analysis.py | LOW | HIGH | subprocess module import | CWE-78 |
| run\_comparative\_analysis.py | LOW | HIGH | subprocess.run() call | CWE-78 |
| run\_comparative\_analysis.py | LOW | HIGH | subprocess in analysis script | CWE-78 |
| gateway.py (legacy) | MEDIUM | MEDIUM | Unspecified medium issue | Review required |
| gateway/app/ (production) | NOT SCANNED | N/A | Must add bandit to CI — P1-10 | Add to pipeline |

Note: The subprocess findings in run\_comparative\_analysis.py are expected for a benchmarking/analysis script and acceptable at LOW severity. The gateway.py MEDIUM finding requires review. The production gateway/app/ must be scanned before M1 quality gate.