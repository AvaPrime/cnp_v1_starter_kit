# Codessa Node Protocol v1 — Starter Kit

> **One protocol. Every node. Infinite scale.**

[![CI](https://github.com/AvaPrime/cnp_v1_starter_kit/actions/workflows/ci.yml/badge.svg)](https://github.com/AvaPrime/cnp_v1_starter_kit/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-70%25-brightgreen)](gateway/coverage.xml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](gateway/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

CNP v1 is a lightweight IoT node protocol built for ESP32 nodes communicating with a Python FastAPI gateway over HTTP and MQTT. It handles the full node lifecycle — registration, heartbeats, telemetry events, commands, error reporting, and OTA — with a clean structured envelope schema and per-node HMAC authentication.

---

## Repository layout

```
cnp_v1_starter_kit/
├── gateway/                 # Production FastAPI gateway (Python 3.11+)
│   ├── app/
│   │   ├── api/             # routes.py, compat.py, admin.py
│   │   ├── core/            # auth, config, db, mqtt_client, rate_limit, registry, storage
│   │   └── models/          # Pydantic schemas
│   ├── tests/               # pytest suite (125 tests, ≥70% coverage)
│   ├── pyproject.toml       # Dependencies and tool config
│   └── Dockerfile           # Multi-stage production image
├── firmware/                # PlatformIO ESP32-C3 project
│   ├── include/             # Header files (Application, Protocol, Transport, ...)
│   └── src/                 # Implementation + example modules
├── db/migrations/           # SQL migration files
├── docs/
│   ├── api/admin.md         # Admin endpoint reference
│   ├── DEPLOYMENT.md        # Production deployment guide
│   ├── TEST_FLOW.md         # Manual test flow (curl)
│   └── schemas/             # CNP message and node registry schemas
├── examples/
│   ├── config.node.example.json
│   └── mosquitto.conf       # Local dev MQTT broker config
├── legacy/                  # Archived root-level flat files — do not use
│   └── ARCHIVED.md          # Explains what each file is and its equivalent
├── cnp_v1_schemas.json      # JSON Schema for all CNP message types
├── cnp_v1_unified_spec.md   # Full protocol specification
├── docker-compose.yml       # Gateway + Mosquitto — one-command local stack
├── .env.example             # Required environment variables (copy to .env)
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE                  # MIT
├── SECURITY.md
└── TLS_SETUP.md             # MQTT TLS configuration guide
```

---

## Architecture

```
ESP32-C3 Node(s)
  │  Wi-Fi → HTTP POST   (Phase 1–5)
  │  Wi-Fi → MQTT        (Phase 6+)
  ▼
┌─────────────────────────────────────────────────────┐
│  CNP Gateway  (gateway/app/)                         │
│                                                      │
│  FastAPI + aiosqlite (WAL mode)                      │
│  Endpoints: /api/node/* — node lifecycle             │
│             /api/nodes/* — dashboard & commands      │
│             /api/fleet/* — admin operations          │
│             /v1/compat/* — backward compatibility    │
│                                                      │
│  MQTT Bridge ─────────────────────────────────────┐ │
│  subscribe: cnp/v1/nodes/+/#                      │ │
│  publish:   cnp/v1/nodes/{id}/cmd/in              │ │
└───────────────────────────────┬───────────────────┘─┘
                                │
                     ┌──────────┴──────────┐
                     │  Mosquitto (MQTT)    │
                     └─────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
  [MEMORY BRIDGE HOOK]    SQLite DB             REST API
  Forward events to        nodes / events        Dashboard
  Codessa Memory Cortex    commands / errors     Ava Prime agents
  (Supabase / ChromaDB)
```

The Memory Bridge Hook is a labelled integration point in `gateway/app/api/routes.py:node_event()` — plug in your Codessa Core forwarding call there.

---

## Quick start

### Option A — Docker Compose (recommended)

Starts the gateway and a local Mosquitto broker in one command.

```bash
# 1. Clone
git clone https://github.com/AvaPrime/cnp_v1_starter_kit.git
cd cnp_v1_starter_kit

# 2. Configure (required — set BOOTSTRAP_TOKEN and ADMIN_TOKEN)
cp .env.example .env
# Edit .env with your real token values:
#   BOOTSTRAP_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))")
#   ADMIN_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))")

# 3. Start
docker compose up

# Gateway API: http://localhost:8080/api/health
# MQTT broker:  localhost:1883
```

### Option B — Local Python

```bash
cd gateway

# 1. Create virtual environment
python -m venv .venv && source .venv/bin/activate

# 2. Install
pip install -e ".[all-dev]"

# 3. Configure
export BOOTSTRAP_TOKEN="$(python -c "import secrets; print(secrets.token_hex(32))")"
export ADMIN_TOKEN="$(python -c "import secrets; print(secrets.token_hex(32))")"

# 4. Run
uvicorn app.main:app --reload --port 8080
```

### Verify it's running

```bash
curl http://localhost:8080/api/health
# {"status":"ok","version":"0.2.0","db_ok":true,"ts_utc":"..."}
```

---

## Run the smoke test (no hardware needed)

```bash
# Simulates: hello → heartbeat → event → command → ack
BOOTSTRAP_TOKEN=your-token bash test_flow.sh
```

---

## API reference

### Node → Gateway (authenticated with X-CNP-Node-Token)

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Gateway health — DB status, version |
| `/api/node/hello` | POST | Node registration (on boot) |
| `/api/node/heartbeat` | POST | Alive ping (every 30s) |
| `/api/node/event` | POST | Report a telemetry or system event |
| `/api/node/state` | POST | Full state snapshot |
| `/api/node/error` | POST | Error report |
| `/api/node/command_result` | POST | Command acknowledgment |
| `/api/node/commands/{node_id}` | GET | Poll for pending commands |

### Dashboard / Ava Prime (no auth required on read endpoints)

| Endpoint | Method | Description |
|---|---|---|
| `/api/nodes` | GET | List nodes (filter: `?status=online`) |
| `/api/nodes/{node_id}` | GET | Single node detail |
| `/api/nodes/{node_id}/commands` | POST | Issue command to a node |
| `/api/nodes/{node_id}/config` | PATCH | Update node config intervals |
| `/api/events` | GET | Recent events (filter: `?priority=high`) |
| `/api/alerts` | GET | High/critical events in last 24 hours |
| `/api/summary` | GET | Fleet-level counts |

### Admin (requires X-CNP-Admin-Token — see [docs/api/admin.md](docs/api/admin.md))

| Endpoint | Method | Description |
|---|---|---|
| `/api/fleet/status` | GET | Node counts by zone and status |
| `/api/nodes/{node_id}/provision` | POST | Generate per-node secret (shown once) |
| `/api/nodes/{node_id}/rotate-secret` | POST | Rotate per-node secret |

### V1 compatibility (`/v1/compat/node/*`)

Legacy endpoint aliases that accept the old `protocol` / `timestamp` key names and translate them to CNP v2 envelopes. See [docs/schemas/cnp_v1_message_schema.md](docs/schemas/cnp_v1_message_schema.md).

---

## Build your first node

### Step 1 — Copy the skeleton

```cpp
// Start from firmware/src/ — copy modules_ExampleClimateModule.cpp
// Rename to your node: modules_KitchenMotionModule.cpp
```

### Step 2 — Set identity (firmware/config/default_config.h)

```cpp
#define NODE_ID    "cnp-kitchen-motion-01"
#define NODE_TYPE  "sensor"
#define WIFI_SSID  "your-network"
// ... see default_config.h for all settings
```

### Step 3 — Implement readSensors()

```cpp
bool readSensors(SensorData& data) {
    data.motion_detected = digitalRead(PIR_PIN) == HIGH;
    data.valid = true;
    return data.valid;
}
```

### Step 4 — Flash

```bash
cd firmware
pio run -t upload
pio device monitor    # watch the node register and send heartbeats
```

The node will self-register via `/api/node/hello` on boot and start appearing in `/api/nodes`.

---

## Issue a command

```bash
curl -X POST http://localhost:8080/api/nodes/cnp-kitchen-motion-01/commands \
  -H "Content-Type: application/json" \
  -d '{
    "command_type": "set_relay",
    "category": "control",
    "timeout_ms": 5000,
    "arguments": { "state": "on" }
  }'
```

The node picks it up on its next poll cycle (~5 seconds), executes it, and sends a `command_result`.

---

## Phase roadmap

| Phase | Status | Goal |
|---|---|---|
| **1** | ✅ Complete | One node, HTTP, local gateway, SQLite |
| **2** | ✅ Complete | Modular gateway, per-node auth, MQTT bridge |
| **3** | 🔄 In progress | Dashboard, live node status UI |
| **4** | Planned | Decision rules — if temp > 30 → command fan |
| **5** | Planned | Memory Cortex bridge — events into Codessa Core |
| **6** | Planned | Multi-node fleet validation |
| **7** | Planned | Full MQTT transport (replace HTTP polling) |

---

## Authentication

### Node tokens

CNP v1 uses a two-stage auth model:

**Stage 1 — Bootstrap:** All nodes use the shared `BOOTSTRAP_TOKEN` for their first `/api/node/hello`. This is a gateway-wide secret stored in the environment.

**Stage 2 — Per-node secrets:** After registration, call `POST /api/nodes/{id}/provision` (admin endpoint) to generate a unique HMAC secret for the node. Store it in NVS on the device. The node derives its token as:

```
token = HMAC-SHA256(SHA256(node_secret), node_id)
```

Send as: `X-CNP-Node-Token: <token>`

Per-node secrets can be rotated without reflashing via `POST /api/nodes/{id}/rotate-secret`.

### Admin token

Admin operations require a separate `ADMIN_TOKEN` environment variable and `X-CNP-Admin-Token` header. See [docs/api/admin.md](docs/api/admin.md).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, commit conventions, and the PR process.

## Security

See [SECURITY.md](SECURITY.md) for the vulnerability disclosure policy and production security hardening checklist.

## License

[MIT](LICENSE) — © 2026 Ava Prime / Codessa OS
