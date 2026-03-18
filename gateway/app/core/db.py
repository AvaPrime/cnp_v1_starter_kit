from __future__ import annotations
import aiosqlite

SCHEMA_SQL = """
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

CREATE TABLE IF NOT EXISTS node_config (
  node_id TEXT PRIMARY KEY REFERENCES nodes(node_id),
  heartbeat_interval_sec INTEGER NOT NULL DEFAULT 60,
  report_interval_sec INTEGER NOT NULL DEFAULT 60,
  permissions_json TEXT,
  custom_json TEXT,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL UNIQUE,
  node_id TEXT NOT NULL,
  ts_utc TEXT NOT NULL,
  category TEXT NOT NULL,
  event_type TEXT NOT NULL,
  priority TEXT NOT NULL,
  requires_ack INTEGER NOT NULL DEFAULT 0,
  body_json TEXT NOT NULL
);

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
  completed_ts_utc TEXT
);

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
  diagnostics_json TEXT
);

CREATE TABLE IF NOT EXISTS acks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL UNIQUE,
  node_id TEXT NOT NULL,
  ack_type TEXT NOT NULL,
  target_message_id TEXT NOT NULL,
  result TEXT NOT NULL,
  reason TEXT,
  ts_utc TEXT NOT NULL
);
"""


async def init_db(path: str) -> None:
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()
