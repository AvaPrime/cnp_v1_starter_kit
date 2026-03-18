# CNP v1 Starter Kit

A production-oriented starter kit for the **Codessa Node Protocol v1 (CNP v1)**. This kit provides:

- A formal message schema and validation rules
- A node registry schema for gateway/device management
- A modular ESP32 firmware skeleton in C++ (Arduino framework)
- A Python gateway skeleton with MQTT, SQLite registry, and REST API
- Test flows, validation scripts, and benchmark scaffolding
- Deployment notes and configuration examples

## Architecture

```text
ESP32 Node(s)
   ├─ persistent identity (Preferences/NVS)
   ├─ registration / heartbeat / event queue / command handler
   ├─ OTA update client
   └─ MQTT transport
            ↓
      MQTT Broker
            ↓
 Python Gateway (FastAPI + MQTT client + SQLite)
   ├─ registry
   ├─ command dispatcher
   ├─ event ingestion
   ├─ timeout/offline detection
   └─ REST API
            ↓
   Codessa Core / Memory / Dashboard
```

## Contents

```text
docs/
  schemas/
    cnp_v1_message_schema.md
    node_registry_schema.md
firmware/
  platformio.ini
  include/
  src/
  config/
gateway/
  requirements.txt
  app/
  tests/
scripts/
  validate_schemas.py
  benchmark_gateway.py
examples/
  config.node.example.json
  mosquitto.conf
```

## Protocol summary

CNP v1 uses a consistent envelope for all packets:

```json
{
  "protocol_version": "CNPv1",
  "message_type": "heartbeat",
  "message_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  "node_id": "cnp-office-climate-01",
  "ts_utc": "2026-03-18T10:21:00Z",
  "qos": 1,
  "payload": {}
}
```

## MQTT topic conventions

```text
cnp/v1/nodes/{node_id}/hello
cnp/v1/nodes/{node_id}/heartbeat
cnp/v1/nodes/{node_id}/state
cnp/v1/nodes/{node_id}/events
cnp/v1/nodes/{node_id}/errors
cnp/v1/nodes/{node_id}/ack
cnp/v1/nodes/{node_id}/cmd/in
cnp/v1/nodes/{node_id}/cmd/out
```

## Quick start

### 1) Gateway

```bash
cd gateway
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Environment variables:

```bash
export MQTT_BROKER_HOST=127.0.0.1
export MQTT_BROKER_PORT=1883
export MQTT_USERNAME=
export MQTT_PASSWORD=
export GATEWAY_DB_PATH=./cnp_gateway.db
export CNP_OFFLINE_AFTER_SECONDS=180
```

### 2) Firmware

Use PlatformIO or Arduino-compatible build tooling. PlatformIO is recommended for repeatable builds.

```bash
cd firmware
pio run
pio run -t upload
```

### 3) Validation

```bash
python scripts/validate_schemas.py
pytest gateway/tests -q
python scripts/benchmark_gateway.py
```

## Design decisions

- **Transport:** MQTT for durable pub/sub and low device overhead
- **Persistence:** ESP32 NVS via Preferences; gateway SQLite for initial deployments
- **Identity:** deterministic, human-readable `node_id` plus immutable device UID
- **Reliability:** local queue + message acknowledgment + offline timeout detection
- **Extensibility:** derived projects only implement sensor/actuator adapters
- **OTA:** HTTPS OTA abstraction hook included in firmware skeleton

## Production notes

- Add TLS to MQTT in production.
- Move SQLite to PostgreSQL when scaling beyond early deployments.
- Use signed firmware manifests and verified HTTPS OTA in production.
- Add per-node secrets or client certificates before field deployment.

## Immediate next step

Implement one concrete node by creating a subclass of `BaseModule` in `firmware/src/modules/` and wiring its telemetry/events into `Application::loop()`.
