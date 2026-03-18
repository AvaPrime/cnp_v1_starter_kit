# First Test Flow

## Goal

Verify that a newly flashed node can register, heartbeat, receive a command, return a result, and be marked offline after timeout.

## Prerequisites

- Mosquitto broker running
- Gateway running on port 8080
- One ESP32 node flashed with starter firmware
- Node configured with correct Wi-Fi and broker settings

## Scenario 1: Registration

1. Power on the node.
2. Observe MQTT topic:
   `cnp/v1/nodes/{node_id}/hello`
3. Confirm gateway emits `register_ack`.
4. Call:
   ```bash
   curl http://localhost:8080/api/nodes
   ```
5. Verify node row exists and `status=online`.

### Pass criteria
- Node appears in registry within 10 seconds.

## Scenario 2: Heartbeat

1. Wait one heartbeat interval.
2. Confirm `last_seen_utc` updates in `/api/nodes/{node_id}`.
3. Confirm `queue_depth`, `free_heap_bytes`, and `last_rssi` are populated.

### Pass criteria
- Heartbeat update latency under 3 seconds on local broker.

## Scenario 3: Command round-trip

1. Send command:
   ```bash
   curl -X POST http://localhost:8080/api/nodes/{node_id}/commands \
     -H "Content-Type: application/json" \
     -d '{"command_type":"set_relay","category":"control","timeout_ms":5000,"arguments":{"state":"on"}}'
   ```
2. Observe publish on:
   `cnp/v1/nodes/{node_id}/cmd/in`
3. Confirm node publishes `command_result` to:
   `cnp/v1/nodes/{node_id}/cmd/out`
4. Query gateway database or API to verify command status changed from `queued` to `executed`.

### Pass criteria
- End-to-end command completion under 2 seconds on LAN.

## Scenario 4: Offline detection

1. Power off the node.
2. Wait `offline_after_sec + 15 sec`.
3. Confirm API reports node `status=offline`.

### Pass criteria
- Node marked offline automatically.

## Scenario 5: Error path

1. Send unsupported command.
2. Confirm node returns `status=error` or `rejected`.
3. Confirm gateway stores the result.

## Performance benchmarks

- Registration handshake < 500 ms broker-to-gateway on LAN
- Sustained heartbeat ingest: 100 msgs/min/node for 20 nodes on laptop-class hardware
- Event insert p95 < 25 ms using SQLite on SSD
- Command dispatch p95 < 150 ms gateway-side before node execution

## Automated validation

- `python scripts/validate_schemas.py`
- `pytest gateway/tests -q`
- `python scripts/benchmark_gateway.py`
