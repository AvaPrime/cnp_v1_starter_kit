# Contributing to CNP v1 Starter Kit

Thank you for your interest in contributing to the Codessa Node Protocol. This guide covers everything you need to get from zero to a passing pull request.

---

## Table of contents

1. [What we welcome](#what-we-welcome)
2. [Development setup](#development-setup)
3. [Running tests](#running-tests)
4. [Code style](#code-style)
5. [Commit conventions](#commit-conventions)
6. [Pull request process](#pull-request-process)
7. [Quality gates](#quality-gates)
8. [Adding a new node type](#adding-a-new-node-type)
9. [Firmware contributions](#firmware-contributions)

---

## What we welcome

- **Bug fixes** — especially anything that improves reliability, security, or protocol correctness
- **Test coverage** — more tests are always welcome; current target is ≥80%
- **Documentation improvements** — corrections, examples, translations
- **New node type examples** — additional firmware sketches in `firmware/src/modules_*.cpp`
- **Protocol extensions** — open an issue first to discuss schema changes before writing code
- **Performance improvements** — benchmarks in `analysis/` help validate claims

We are **not** currently accepting:
- Changes to `legacy/` — those files are archived
- New runtime dependencies without a discussion issue first
- Breaking changes to the CNP v1 envelope schema

---

## Development setup

### Prerequisites

- Python 3.11 or 3.12
- [PlatformIO](https://platformio.org/) (for firmware contributions only)
- Docker + Docker Compose (for integration testing)

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/AvaPrime/cnp_v1_starter_kit.git
cd cnp_v1_starter_kit/gateway
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

### 2. Install all development dependencies

```bash
# Using pyproject.toml (recommended)
pip install -e ".[all-dev]"

# Or using requirements.txt (fallback)
pip install -r requirements.txt
```

### 3. Configure your environment

```bash
cp ../.env.example ../.env
# Edit .env and set BOOTSTRAP_TOKEN and ADMIN_TOKEN to any non-empty strings for local dev
```

### 4. Run the gateway locally

```bash
# Option A — direct (inside gateway/)
uvicorn app.main:app --reload --port 8080

# Option B — Docker Compose (from repo root)
docker compose up
```

### 5. Verify everything works

```bash
# Health check
curl http://localhost:8080/api/health

# Run the curl smoke test
bash test_flow.sh
```

---

## Running tests

All tests live in `gateway/tests/`. Run from the `gateway/` directory:

```bash
# All tests with coverage report
pytest

# Fast run without coverage (during active development)
pytest --no-cov -x

# Run a specific test file
pytest tests/test_mqtt_handlers.py -v

# Run tests matching a keyword
pytest -k "test_handle_hello" -v
```

### Coverage requirement

The CI pipeline enforces **≥60% coverage** (`--cov-fail-under=60` in `pyproject.toml`). PRs that drop coverage below this threshold will not be merged. The current coverage target trajectory is:

| Phase | Floor |
|---|---|
| Phase 1 (current) | 60% |
| Phase 2 | 70% |
| Phase 3 | 80% |
| Phase 4 (public release) | 85% |

If your PR adds untested code, add tests before opening the PR.

---

## Code style

The project uses **ruff** for linting and formatting, and **mypy** for type checking. Both run in CI and will block merge if they fail.

```bash
# Lint
ruff check app tests

# Auto-fix safe issues
ruff check app tests --fix

# Type check
mypy app --ignore-missing-imports
```

Key conventions:
- All source files use `from __future__ import annotations`
- Use `async with db_connect(path) as db:` — never bare `aiosqlite.connect()`
- Pydantic models for all request bodies — no raw `await request.json()` with manual validation
- SQL queries: parameterized only — no f-string or `.format()` in query strings
- Log structured key=value pairs: `log.info("event.name key=%s", value)`

---

## Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`

Scopes: `gateway`, `firmware`, `mqtt`, `auth`, `db`, `api`, `docs`, `ci`

Examples:
```
feat(api): add pagination cursor to /api/events
fix(mqtt): correct wildcard subscription pattern to cnp/v1/nodes/+/#
test(mqtt): add handler unit tests for hello and heartbeat paths
docs(api): document admin endpoint auth requirements
chore(deps): upgrade pytest-asyncio to 0.23.8
```

---

## Pull request process

1. **Open an issue first** for anything non-trivial — agree on approach before writing code
2. **Fork the repo** and create a branch: `git checkout -b fix/mqtt-wildcard`
3. **Write tests first** if fixing a bug — the test should fail before your fix and pass after
4. **Run the full quality gate locally** before pushing:
   ```bash
   cd gateway
   ruff check app tests
   mypy app --ignore-missing-imports
   bandit -r app -ll -x tests
   pytest
   ```
5. **Open a PR** against `main` with:
   - A clear description of what changed and why
   - Reference to the related issue: `Closes #42`
   - Confirmation that all quality gates pass locally
6. **Address review feedback** — at least one approval required before merge
7. **Squash commits** on merge — keep `main` history linear

### PR template checklist

- [ ] Tests added/updated for changed behaviour
- [ ] Coverage did not decrease
- [ ] `ruff check` passes
- [ ] `mypy` passes
- [ ] `bandit -r app -ll` returns no MEDIUM+ severity findings
- [ ] Documentation updated if API or config changed
- [ ] CHANGELOG.md updated under `[Unreleased]`

---

## Quality gates

All of these must pass before a PR can be merged. They run automatically via GitHub Actions on every push and PR.

| Gate | Tool | Threshold |
|---|---|---|
| Lint | `ruff check` | 0 errors |
| Type check | `mypy` | 0 errors |
| Security | `bandit -ll` | 0 MEDIUM+ severity in `app/` |
| Dependency audit | `pip-audit` | 0 known CVEs |
| Tests | `pytest` | All pass |
| Coverage | `pytest-cov` | ≥60% (rising each phase) |
| Docker build | `docker build` | Must succeed |
| Repo hygiene | Custom checks | No `.db` files, LICENSE present |

---

## Adding a new node type

1. Copy `firmware/src/modules_ExampleClimateModule.cpp` to `firmware/src/modules_YourModule.cpp`
2. Implement `readSensors()` and optionally `handleActuator()`
3. Update `firmware/src/Application.cpp` to register your module
4. Add your node type to the `CNP-SPEC-001` schema in `cnp_v1_schemas.json`
5. Write a test envelope in `gateway/tests/conftest.py` (`make_event_envelope`)
6. Add an example config to `examples/`

---

## Firmware contributions

Firmware lives in `firmware/` and is built with PlatformIO.

```bash
cd firmware
pio run                  # build
pio run -t upload        # flash to connected ESP32-C3
pio device monitor       # serial monitor at 115200 baud
```

For firmware PRs, include:
- What hardware you tested on (board, sensor model)
- Serial log snippet showing the node going through the full lifecycle (hello → heartbeat → event)
- Any changes to `platformio.ini` with justification

---

## Questions?

Open a [GitHub Discussion](https://github.com/AvaPrime/cnp_v1_starter_kit/discussions) or file an issue. For security vulnerabilities, see [SECURITY.md](SECURITY.md).
