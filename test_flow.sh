#!/usr/bin/env bash
# ================================================================
#  CNP v1 Starter Kit — First Test Flow
#  File: test_flow.sh
#
#  This script simulates a complete node lifecycle against your
#  local gateway using curl, so you can verify the full chain
#  BEFORE touching any hardware.
#
#  Usage:
#    chmod +x test_flow.sh
#    ./test_flow.sh
#
#  Prerequisites:
#    1. Gateway running:  python gateway.py
#    2. curl installed
#    3. jq installed (optional, for pretty output)
# ================================================================

GATEWAY="http://localhost:5000"
TOKEN="YOUR_NODE_TOKEN"
NODE_ID="cnp-office-temp-01"

# Colors
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

ok()   { echo -e "${GREEN}  ✓  $1${RESET}"; }
info() { echo -e "${CYAN}  ▶  $1${RESET}"; }
warn() { echo -e "${YELLOW}  ⚠  $1${RESET}"; }
fail() { echo -e "${RED}  ✗  $1${RESET}"; exit 1; }

call() {
  local label="$1"
  local method="$2"
  local path="$3"
  local data="$4"

  echo ""
  info "$label"
  echo "  ${method} ${GATEWAY}${path}"

  if [ "$method" = "GET" ]; then
    RESPONSE=$(curl -s -w "\n%{http_code}" \
      -H "X-CNP-Token: $TOKEN" \
      "${GATEWAY}${path}")
  else
    RESPONSE=$(curl -s -w "\n%{http_code}" \
      -X "$method" \
      -H "Content-Type: application/json" \
      -H "X-CNP-Token: $TOKEN" \
      -d "$data" \
      "${GATEWAY}${path}")
  fi

  HTTP_CODE=$(echo "$RESPONSE" | tail -1)
  BODY=$(echo "$RESPONSE" | head -n -1)

  if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
    ok "HTTP $HTTP_CODE"
    echo "  Response: $(echo $BODY | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin), indent=2))' 2>/dev/null || echo $BODY)"
  else
    fail "HTTP $HTTP_CODE — $BODY"
  fi

  sleep 0.5
}

# ================================================================
echo ""
echo "================================================================"
echo "  Codessa Node Protocol v1 — First Test Flow"
echo "  Gateway: $GATEWAY"
echo "  Node:    $NODE_ID"
echo "================================================================"

# ----------------------------------------------------------------
# STEP 1: Health check
# ----------------------------------------------------------------
echo ""
echo -e "${YELLOW}━━━ STEP 1: Gateway Health ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
call "Health check" "GET" "/health"

# ----------------------------------------------------------------
# STEP 2: Node HELLO (registration)
# ----------------------------------------------------------------
echo ""
echo -e "${YELLOW}━━━ STEP 2: Node Hello (Registration) ━━━━━━━━━━━━━━━━━━━${RESET}"
call "Node hello" "POST" "/api/node/hello" '{
  "protocol": "CNPv1",
  "message_type": "hello",
  "node_id": "'"$NODE_ID"'",
  "timestamp": "2026-03-18T10:00:00Z",
  "payload": {
    "node_name": "Office Climate Node",
    "node_type": "sensor",
    "zone": "office",
    "firmware_version": "1.0.0",
    "capabilities": {
      "sensors": ["temperature", "humidity"],
      "actuators": [],
      "connectivity": ["wifi"],
      "power_mode": "usb"
    }
  }
}'

# ----------------------------------------------------------------
# STEP 3: Heartbeat
# ----------------------------------------------------------------
echo ""
echo -e "${YELLOW}━━━ STEP 3: Heartbeat ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
call "Heartbeat" "POST" "/api/node/heartbeat" '{
  "protocol": "CNPv1",
  "message_type": "heartbeat",
  "node_id": "'"$NODE_ID"'",
  "timestamp": "2026-03-18T10:00:30Z",
  "payload": {
    "status": "online",
    "uptime_sec": 30,
    "battery": -1,
    "wifi_rssi": -58
  }
}'

# ----------------------------------------------------------------
# STEP 4: Telemetry event (normal)
# ----------------------------------------------------------------
echo ""
echo -e "${YELLOW}━━━ STEP 4: Telemetry Event ━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
call "Temperature reading" "POST" "/api/node/event" '{
  "protocol": "CNPv1",
  "message_type": "event",
  "node_id": "'"$NODE_ID"'",
  "timestamp": "2026-03-18T10:01:00Z",
  "payload": {
    "event_id": "evt-000001",
    "event_type": "temperature_reading",
    "category": "telemetry",
    "priority": "normal",
    "data": {
      "temperature_c": 27.4,
      "humidity_pct": 61.0
    }
  }
}'

# ----------------------------------------------------------------
# STEP 5: Alert event (high priority)
# ----------------------------------------------------------------
echo ""
echo -e "${YELLOW}━━━ STEP 5: Alert Event (High Priority) ━━━━━━━━━━━━━━━━${RESET}"
call "Temperature alert" "POST" "/api/node/event" '{
  "protocol": "CNPv1",
  "message_type": "event",
  "node_id": "'"$NODE_ID"'",
  "timestamp": "2026-03-18T10:02:00Z",
  "payload": {
    "event_id": "evt-000002",
    "event_type": "temperature_threshold_exceeded",
    "category": "alert",
    "priority": "high",
    "data": {
      "temperature_c": 32.1,
      "threshold_c": 30.0
    }
  }
}'

# ----------------------------------------------------------------
# STEP 6: Error report
# ----------------------------------------------------------------
echo ""
echo -e "${YELLOW}━━━ STEP 6: Error Report ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
call "Sensor error" "POST" "/api/node/error" '{
  "protocol": "CNPv1",
  "message_type": "error",
  "node_id": "'"$NODE_ID"'",
  "timestamp": "2026-03-18T10:02:30Z",
  "payload": {
    "error_code": "SENSOR_READ_FAIL",
    "error_msg": "DHT22 returned NaN on read attempt",
    "recoverable": true
  }
}'

# ----------------------------------------------------------------
# STEP 7: Issue a command from gateway → node
# ----------------------------------------------------------------
echo ""
echo -e "${YELLOW}━━━ STEP 7: Issue Command (Gateway → Node) ━━━━━━━━━━━━━${RESET}"
CMD_RESPONSE=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "'"$NODE_ID"'",
    "command_type": "set_relay",
    "category": "control",
    "params": { "state": "on" }
  }' \
  "${GATEWAY}/api/commands")
echo "  Response: $CMD_RESPONSE"
CMD_ID=$(echo $CMD_RESPONSE | python3 -c 'import sys,json; print(json.load(sys.stdin).get("command_id","unknown"))' 2>/dev/null)
ok "Command issued: $CMD_ID"

# ----------------------------------------------------------------
# STEP 8: Node polls for pending command
# ----------------------------------------------------------------
echo ""
echo -e "${YELLOW}━━━ STEP 8: Node Polls for Commands ━━━━━━━━━━━━━━━━━━━━${RESET}"
call "Poll commands" "GET" "/api/node/commands/$NODE_ID"

# ----------------------------------------------------------------
# STEP 9: Node sends command acknowledgment
# ----------------------------------------------------------------
echo ""
echo -e "${YELLOW}━━━ STEP 9: Command Acknowledgment ━━━━━━━━━━━━━━━━━━━━━${RESET}"
call "Command ACK" "POST" "/api/node/command_result" '{
  "protocol": "CNPv1",
  "message_type": "command_result",
  "node_id": "'"$NODE_ID"'",
  "timestamp": "2026-03-18T10:03:00Z",
  "payload": {
    "command_id": "'"$CMD_ID"'",
    "status": "executed"
  }
}'

# ----------------------------------------------------------------
# STEP 10: Inspect the registry
# ----------------------------------------------------------------
echo ""
echo -e "${YELLOW}━━━ STEP 10: Inspect Node Registry ━━━━━━━━━━━━━━━━━━━━━${RESET}"
call "List all nodes" "GET" "/api/nodes"

echo ""
call "Get events" "GET" "/api/events?limit=10"

echo ""
call "Get alerts" "GET" "/api/alerts"

# ----------------------------------------------------------------
# DONE
# ----------------------------------------------------------------
echo ""
echo "================================================================"
echo -e "${GREEN}  ✓  Test flow complete.${RESET}"
echo ""
echo "  Next steps:"
echo "    1. Flash cnp_node_skeleton.ino to your ESP32-C3"
echo "    2. Edit NODE_ID, WIFI_SSID, GATEWAY_URL in the sketch"
echo "    3. Watch the gateway logs for real hardware events"
echo "    4. Open http://localhost:5000/api/nodes in your browser"
echo "================================================================"
echo ""
