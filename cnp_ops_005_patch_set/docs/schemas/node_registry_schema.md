# Node Registry Schema

The gateway maintains a local registry for identity, capability, health, status, and metadata. The starter kit uses SQLite.

## 1. Table: `nodes`

```sql
CREATE TABLE IF NOT EXISTS nodes (
  node_id TEXT PRIMARY KEY,
  device_uid TEXT NOT NULL,
  node_name TEXT NOT NULL,
  node_type TEXT NOT NULL,
  protocol_version TEXT NOT NULL,
  firmware_version TEXT NOT NULL,
  hardware_model TEXT NOT NULL,
  capabilities_json TEXT NOT NULL,
  config_version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'unknown',
  last_seen_utc TEXT,
  first_seen_utc TEXT NOT NULL,
  boot_reason TEXT,
  heartbeat_interval_sec INTEGER NOT NULL DEFAULT 60,
  offline_after_sec INTEGER NOT NULL DEFAULT 180,
  last_rssi INTEGER,
  battery_pct REAL,
  free_heap_bytes INTEGER,
  queue_depth INTEGER NOT NULL DEFAULT 0,
  supports_ota INTEGER NOT NULL DEFAULT 0,
  ota_channel TEXT DEFAULT 'stable',
  ota_last_result TEXT,
  tags_json TEXT DEFAULT '[]',
  metadata_json TEXT DEFAULT '{}'
);
```

## 2. Table: `events`

```sql
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL UNIQUE,
  node_id TEXT NOT NULL,
  ts_utc TEXT NOT NULL,
  category TEXT NOT NULL,
  event_type TEXT NOT NULL,
  priority TEXT NOT NULL,
  requires_ack INTEGER NOT NULL DEFAULT 0,
  body_json TEXT NOT NULL,
  FOREIGN KEY(node_id) REFERENCES nodes(node_id)
);
```

## 3. Table: `commands`

```sql
CREATE TABLE IF NOT EXISTS commands (
  command_id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL,
  command_type TEXT NOT NULL,
  category TEXT NOT NULL,
  issued_by TEXT NOT NULL,
  issued_ts_utc TEXT NOT NULL,
  status TEXT NOT NULL,
  timeout_ms INTEGER NOT NULL,
  arguments_json TEXT NOT NULL,
  result_code TEXT,
  result_details_json TEXT,
  completed_ts_utc TEXT,
  FOREIGN KEY(node_id) REFERENCES nodes(node_id)
);
```

## 4. Table: `errors`

```sql
CREATE TABLE IF NOT EXISTS errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL UNIQUE,
  node_id TEXT NOT NULL,
  ts_utc TEXT NOT NULL,
  severity TEXT NOT NULL,
  domain TEXT NOT NULL,
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  recoverable INTEGER NOT NULL,
  diagnostics_json TEXT,
  FOREIGN KEY(node_id) REFERENCES nodes(node_id)
);
```

## 5. Table: `acks`

```sql
CREATE TABLE IF NOT EXISTS acks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL UNIQUE,
  node_id TEXT NOT NULL,
  ack_type TEXT NOT NULL,
  target_message_id TEXT NOT NULL,
  result TEXT NOT NULL,
  reason TEXT,
  ts_utc TEXT NOT NULL,
  FOREIGN KEY(node_id) REFERENCES nodes(node_id)
);
```

## Status field semantics

| Field | Meaning |
|---|---|
| `unknown` | discovered but not validated |
| `registering` | registration pending |
| `online` | recent heartbeat within timeout window |
| `degraded` | heartbeat received but reports warning or poor health |
| `offline` | heartbeat timeout exceeded |
| `blocked` | known device not allowed to operate |
| `retired` | intentionally removed from service |

## Metadata guidance

`metadata_json` can include:

```json
{
  "zone": "office",
  "site": "cape-town-lab",
  "owner": "phoenix",
  "notes": "prototype climate node",
  "module_profile": "climate-v1"
}
```

## Capability guidance

`capabilities_json` mirrors the `hello.payload.capabilities` object. Receivers should never infer capabilities from model names.

## Registry update rules

1. `hello` MUST insert or upsert into `nodes`.
2. `heartbeat` MUST refresh `last_seen_utc`, `last_rssi`, `battery_pct`, `free_heap_bytes`, `queue_depth`.
3. Offline status is set when `now - last_seen_utc > offline_after_sec`.
4. `state_update` SHOULD update `status` if it changes.
5. `event`, `error`, `command_result`, and `ack` MUST be persisted immutably.
