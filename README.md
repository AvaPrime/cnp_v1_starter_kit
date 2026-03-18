# Codessa Node Protocol v1 — Starter Kit

> **One protocol. Every node. Infinite scale.**

---

## What's in this kit

| File | Purpose |
|---|---|
| `cnp_v1_schemas.json` | Full JSON Schema definitions for every CNP message type |
| `node_registry.sql` | SQLite schema — nodes, events, commands, heartbeats, config |
| `cnp_node_skeleton/cnp_node_skeleton.ino` | ESP32-C3 base firmware all nodes inherit from |
| `gateway/gateway.py` | Python FastAPI gateway — receives all node traffic |
| `test_flow.sh` | Curl-based smoke test — validates the full chain without hardware |

---

## Architecture

```
ESP32 Node
  │  (Wi-Fi / HTTP POST)
  ▼
gateway.py  ←──────────────────────────┐
  │  SQLite: nodes, events, commands   │
  │  REST API for dashboard / core     │
  ▼                                    │
Codessa Memory Cortex                  │
  │  Store meaningful events           │
  ▼                                    │
Decision Engine                        │
  │  Trigger rules / automations       │
  └───────────────── Command → Node ───┘
```

---

## Quick start

### 1. Install Python dependencies

```bash
pip install fastapi uvicorn aiosqlite
```

### 2. Start the gateway

```bash
cd gateway
python gateway.py
```

Gateway runs on `http://0.0.0.0:5000`.

### 3. Initialize the database

The gateway does this automatically on first run using `node_registry.sql`.
Or manually:

```bash
sqlite3 codessa_registry.db < node_registry.sql
```

### 4. Run the test flow (no hardware needed)

```bash
chmod +x test_flow.sh
./test_flow.sh
```

This simulates a complete node lifecycle: hello → heartbeat → events → command → ack.

### 5. Flash the ESP32

1. Open `cnp_node_skeleton/cnp_node_skeleton.ino` in Arduino IDE
2. Install ArduinoJson library (Library Manager → search "ArduinoJson")
3. Edit the constants at the top of the file:

```cpp
#define NODE_ID           "cnp-office-temp-01"   // unique per node
#define NODE_NAME         "Office Climate Node"
#define NODE_TYPE         "sensor"
#define NODE_ZONE         "office"
#define WIFI_SSID         "YOUR_WIFI_SSID"
#define WIFI_PASSWORD     "YOUR_WIFI_PASSWORD"
#define GATEWAY_URL       "http://192.168.1.100:5000"  // your machine's LAN IP
#define NODE_TOKEN        "YOUR_NODE_TOKEN"
```

4. Implement `readSensors()` with your sensor logic
5. Flash to ESP32-C3 (Board: `ESP32C3 Dev Module`)

---

## Node naming convention

```
cnp-{zone}-{function}-{index}
```

Examples:
- `cnp-office-temp-01`
- `cnp-entry-motion-01`
- `cnp-lab-relay-01`
- `cnp-bedroom-climate-01`

---

## API reference

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Gateway health check |
| `/api/node/hello` | POST | Node registration |
| `/api/node/heartbeat` | POST | Alive ping |
| `/api/node/event` | POST | Report an event |
| `/api/node/state` | POST | Full state update |
| `/api/node/error` | POST | Error report |
| `/api/node/command_result` | POST | Command acknowledgment |
| `/api/node/commands/{node_id}` | GET | Poll for pending commands |
| `/api/nodes` | GET | List all nodes (dashboard) |
| `/api/nodes/{node_id}` | GET | Single node detail |
| `/api/events` | GET | Recent events |
| `/api/alerts` | GET | Recent high/critical alerts |
| `/api/commands` | POST | Issue command to a node |
| `/api/nodes/{node_id}/config` | PATCH | Update node config |

---

## Build your first node in 4 steps

### Step 1: Copy the skeleton

Start from `cnp_node_skeleton.ino`. Rename it to your node, e.g. `cnp_climate_node.ino`.

### Step 2: Set identity

```cpp
#define NODE_ID   "cnp-office-climate-01"
#define NODE_TYPE "hybrid"  // has sensor + actuator
```

### Step 3: Implement readSensors()

```cpp
bool readSensors(SensorData& data) {
  data.temperature_c = dht.readTemperature();
  data.humidity_pct  = dht.readHumidity();
  data.valid = !isnan(data.temperature_c);
  return data.valid;
}
```

### Step 4: Implement handleActuator() if needed

```cpp
void handleActuator(const char* commandType, JsonObject& params) {
  if (strcmp(commandType, "set_relay") == 0) {
    bool on = strcmp(params["state"], "on") == 0;
    digitalWrite(RELAY_PIN, on ? HIGH : LOW);
  }
}
```

Done. Flash it. It will self-register and start reporting.

---

## Issue a command from your terminal

```bash
curl -X POST http://localhost:5000/api/commands \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "cnp-lab-relay-01",
    "command_type": "set_relay",
    "category": "control",
    "params": { "state": "on" }
  }'
```

The node picks it up on its next poll cycle (~5 seconds), executes it, and sends an ack.

---

## Memory bridge hook

In `gateway.py`, the event handler has a labeled hook for forwarding to Codessa Core:

```python
# --------------------------------------------------------
#  MEMORY BRIDGE HOOK — add your Codessa Core forwarding here
#  Example: await forward_to_memory_cortex(node_id, payload)
# --------------------------------------------------------
```

Plug in Supabase, Firestore, ChromaDB, or your Memory Cortex service here.

---

## CNP v1 message types

### Node → Gateway

| Type | When |
|---|---|
| `hello` | On boot — identity + capabilities |
| `heartbeat` | Every 30s — alive + state |
| `state_update` | On demand — full state snapshot |
| `event` | Something meaningful happened |
| `command_result` | After executing a command |
| `error` | Something went wrong |

### Gateway → Node

| Type | When |
|---|---|
| `register_ack` | Response to hello |
| `command` | Instruction for the node |
| `config_update` | Change intervals/permissions |

---

## Node lifecycle (every new node)

```
Power on
  → connect Wi-Fi
  → send hello
  → receive register_ack + config
  → nodeSetup()
  → main loop:
      every 30s  → heartbeat
      every 60s  → readSensors() → event
      every 5s   → poll for commands
      on error   → sendError()
```

---

## Phase roadmap

| Phase | Goal |
|---|---|
| **1** (now) | One node, HTTP, local gateway, SQLite |
| **2** | Dashboard — live node status in browser |
| **3** | Decision rules — if temp > 30 → command fan |
| **4** | Memory Cortex bridge — meaningful events into long-term storage |
| **5** | Multi-node — second node, confirm protocol scales |
| **6** | MQTT — replace HTTP for lower overhead at scale |

---

## Auth note

CNP v1 uses a shared bearer token (`X-CNP-Token`) for simplicity.

For production: issue a unique token per node stored in `node_config`, validated per-request.

---

*CNP v1 — Codessa Node Protocol. One node at a time.*
