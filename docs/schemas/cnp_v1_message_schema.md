# CNP v1 Message Schema Specification

## 1. Scope

This specification defines all packet types, field formats, validation rules, and topic bindings for the Codessa Node Protocol v1.

CNP v1 is transport-agnostic, but this starter kit binds it to MQTT.

## 2. Common envelope

All packets MUST conform to this envelope.

| Field | Type | Required | Validation |
|---|---|---:|---|
| `protocol_version` | string | yes | MUST equal `CNPv1` |
| `message_type` | string | yes | MUST be one of the defined packet types |
| `message_id` | string | yes | ULID/UUID string, length 20-36 |
| `node_id` | string | yes | `^[a-z0-9-]{3,64}$` |
| `ts_utc` | string | yes | RFC 3339 UTC timestamp ending in `Z` |
| `qos` | integer | yes | MUST be 0 or 1 |
| `correlation_id` | string | no | optional message linkage for replies |
| `payload` | object | yes | packet-specific schema |
| `sig` | string | no | optional signature or HMAC for production |

### Validation rules

1. Unknown top-level fields SHOULD be ignored by receivers unless strict mode is enabled.
2. `message_id` MUST be unique per sender for at least 24 hours.
3. `correlation_id` MUST reference the originating `message_id` when used.
4. Payloads MUST NOT exceed 4096 bytes for regular telemetry/events in v1.
5. Commands MAY allow payloads up to 8192 bytes only for maintenance/configuration use.

## 3. Packet types

### 3.1 `hello`

Published by node at boot or reconnect.

Topic:
`cnp/v1/nodes/{node_id}/hello`

Payload:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `device_uid` | string | yes | immutable silicon or generated installation UID |
| `node_name` | string | yes | human-readable name |
| `node_type` | string | yes | `sensor`, `actuator`, `hybrid`, `gateway` |
| `firmware_version` | string | yes | semver recommended |
| `hardware_model` | string | yes | board/device family |
| `capabilities` | object | yes | sensors/actuators/connectivity |
| `supports_ota` | boolean | yes | whether OTA is available |
| `boot_reason` | string | yes | `power_on`, `reset`, `watchdog`, `ota`, `deep_sleep`, `unknown` |

Acknowledgment:
Gateway publishes `register_ack` to:
`cnp/v1/nodes/{node_id}/ack`

### 3.2 `register_ack`

Published by gateway after accepting/rejecting registration.

Payload:

| Field | Type | Required |
|---|---|---:|
| `accepted` | boolean | yes |
| `gateway_id` | string | yes |
| `assigned_config_version` | integer | yes |
| `heartbeat_interval_sec` | integer | yes |
| `event_batch_max` | integer | yes |
| `offline_after_sec` | integer | yes |
| `reason` | string | no |

### 3.3 `heartbeat`

Published periodically by node.

Topic:
`cnp/v1/nodes/{node_id}/heartbeat`

Payload:

| Field | Type | Required |
|---|---|---:|
| `seq` | integer | yes |
| `uptime_sec` | integer | yes |
| `free_heap_bytes` | integer | yes |
| `wifi_rssi` | integer | no |
| `battery_pct` | number | no |
| `queue_depth` | integer | yes |
| `status` | string | yes |

### 3.4 `state_update`

Published on meaningful state change or periodic snapshot.

Topic:
`cnp/v1/nodes/{node_id}/state`

Payload:

| Field | Type | Required |
|---|---|---:|
| `status` | string | yes |
| `mode` | string | no |
| `fields` | object | yes |
| `changed` | array[string] | yes |

### 3.5 `event`

Published by node for telemetry, alerts, interactions, or system notices.

Topic:
`cnp/v1/nodes/{node_id}/events`

Payload:

| Field | Type | Required |
|---|---|---:|
| `event_type` | string | yes |
| `category` | string | yes |
| `priority` | string | yes |
| `delivery_mode` | string | yes |
| `requires_ack` | boolean | yes |
| `event_seq` | integer | yes |
| `body` | object | yes |

Validation:
- `category` MUST be one of `telemetry`, `alert`, `interaction`, `system`, `security`, `power`.
- `priority` MUST be `low`, `normal`, `high`, or `critical`.
- `delivery_mode` MUST be `fire_and_forget` or `confirm`.
- `requires_ack` MUST be true when `delivery_mode=confirm`.

### 3.6 `ack`

Published by gateway or node to confirm event/command delivery.

Topic:
`cnp/v1/nodes/{node_id}/ack`

Payload:

| Field | Type | Required |
|---|---|---:|
| `ack_type` | string | yes |
| `target_message_id` | string | yes |
| `result` | string | yes |
| `reason` | string | no |

Validation:
- `ack_type` MUST be `registration`, `event`, `command`, or `config`.
- `result` MUST be `accepted`, `processed`, `rejected`, or `failed`.

### 3.7 `command`

Published by gateway to node.

Topic:
`cnp/v1/nodes/{node_id}/cmd/in`

Payload:

| Field | Type | Required |
|---|---|---:|
| `command_id` | string | yes |
| `command_type` | string | yes |
| `category` | string | yes |
| `timeout_ms` | integer | yes |
| `arguments` | object | yes |
| `issued_by` | string | yes |
| `dry_run` | boolean | yes |

Validation:
- `category` MUST be `control`, `configuration`, `maintenance`, or `power`.
- `timeout_ms` MUST be between 100 and 600000.

### 3.8 `command_result`

Published by node after command execution attempt.

Topic:
`cnp/v1/nodes/{node_id}/cmd/out`

Payload:

| Field | Type | Required |
|---|---|---:|
| `command_id` | string | yes |
| `status` | string | yes |
| `duration_ms` | integer | yes |
| `code` | string | yes |
| `details` | object | yes |

Validation:
- `status` MUST be `executed`, `rejected`, `timeout`, `error`, or `dry_run`.
- `code` SHOULD be machine-readable, e.g. `CMD_OK`, `ERR_ARG_INVALID`.

### 3.9 `error`

Published by node or gateway.

Topic:
`cnp/v1/nodes/{node_id}/errors`

Payload:

| Field | Type | Required |
|---|---|---:|
| `severity` | string | yes |
| `domain` | string | yes |
| `code` | string | yes |
| `message` | string | yes |
| `diagnostics` | object | no |
| `recoverable` | boolean | yes |

Validation:
- `severity` MUST be `debug`, `info`, `warning`, `error`, or `critical`.

### 3.10 `config_update`

Published by gateway to node.

Topic:
`cnp/v1/nodes/{node_id}/config`

Payload:

| Field | Type | Required |
|---|---|---:|
| `config_version` | integer | yes |
| `heartbeat_interval_sec` | integer | yes |
| `telemetry_interval_sec` | integer | no |
| `offline_after_sec` | integer | yes |
| `report_rssi` | boolean | yes |
| `module` | object | no |

## 4. Capability object

```json
{
  "sensors": ["temperature", "humidity"],
  "actuators": ["relay"],
  "connectivity": ["wifi"],
  "storage": ["nvs"],
  "power": {
    "source": "usb",
    "battery_supported": false
  }
}
```

## 5. Error code conventions

Format:
`{DOMAIN}_{CLASS}_{NUMBER}`

Examples:
- `NET_TIMEOUT_001`
- `MQTT_AUTH_002`
- `CMD_ARG_003`
- `SENSOR_READ_004`

## 6. JSON Schema draft starter

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["protocol_version", "message_type", "message_id", "node_id", "ts_utc", "qos", "payload"],
  "properties": {
    "protocol_version": { "const": "CNPv1" },
    "message_type": {
      "enum": ["hello", "register_ack", "heartbeat", "state_update", "event", "ack", "command", "command_result", "error", "config_update"]
    },
    "message_id": { "type": "string", "minLength": 20, "maxLength": 36 },
    "node_id": { "type": "string", "pattern": "^[a-z0-9-]{3,64}$" },
    "ts_utc": { "type": "string", "pattern": "Z$" },
    "qos": { "type": "integer", "enum": [0, 1] },
    "correlation_id": { "type": "string" },
    "payload": { "type": "object" },
    "sig": { "type": "string" }
  },
  "additionalProperties": true
}
```
