-- ============================================================
--  CNP EPIC-02 — P2-04
--  Migration: 003_v1_to_v2_schema.sql
--
--  Upgrades an existing V1 (files gateway) SQLite database to
--  the V2 unified schema. Safe to run against a V2 DB that
--  already has the new columns — all ADD COLUMN statements
--  use IF NOT EXISTS via migration script guards.
--
--  Companion CLI: migrate.py --source <path> [--dry-run]
--
--  Column changes:
--    nodes      +9 V2 columns, battery INT→REAL rename compat
--    errors     +severity, +domain, +code alignment
--    commands   params_json→arguments_json, +issued_by, +timeout_ms
--    heartbeats +free_heap_bytes, +queue_depth
--    acks       new table (V1 had none)
--    node_config already present in V1 — extended
--
--  Status enum expansion:
--    V1 had: online | offline | degraded
--    V2 adds: unknown | registering | blocked | retired
--    Existing rows are NOT changed (backward compatible).
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = OFF;  -- relaxed during migration, re-enabled after

-- ============================================================
--  NODES — add 9 V2 columns with safe defaults
-- ============================================================

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    device_uid TEXT NOT NULL DEFAULT '';

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    hardware_model TEXT NOT NULL DEFAULT 'unknown';

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    boot_reason TEXT;

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    config_version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    first_seen_utc TEXT;

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    free_heap_bytes INTEGER;

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    queue_depth INTEGER NOT NULL DEFAULT 0;

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    supports_ota INTEGER NOT NULL DEFAULT 0;

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    ota_channel TEXT DEFAULT 'stable';

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    ota_last_result TEXT;

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    tags_json TEXT DEFAULT '[]';

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    metadata_json TEXT DEFAULT '{}';

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    offline_after_sec INTEGER NOT NULL DEFAULT 180;

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    heartbeat_interval_sec INTEGER NOT NULL DEFAULT 60;

-- Backfill first_seen_utc from registered_at where NULL
UPDATE nodes
SET first_seen_utc = COALESCE(registered_at, strftime('%Y-%m-%dT%H:%M:%SZ','now'))
WHERE first_seen_utc IS NULL;

-- Backfill metadata_json zone from existing zone column
UPDATE nodes
SET metadata_json = json_object('zone', zone)
WHERE zone IS NOT NULL
  AND zone != ''
  AND (metadata_json IS NULL OR metadata_json = '{}');

-- Rename last_seen → last_seen_utc via compat view
-- SQLite cannot rename columns in-place before 3.25.0
-- We use a compat view approach and migrate data via UPDATE
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    last_seen_utc TEXT;

UPDATE nodes
SET last_seen_utc = last_seen
WHERE last_seen_utc IS NULL AND last_seen IS NOT NULL;

-- ============================================================
--  NODES — battery column migration
--  V1: battery INTEGER (-1 sentinel for N/A)
--  V2: battery_pct REAL (NULL for N/A)
-- ============================================================

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    battery_pct REAL;

-- Convert: -1 sentinel → NULL, otherwise cast to REAL
UPDATE nodes
SET battery_pct = CASE
    WHEN battery = -1 THEN NULL
    WHEN battery IS NOT NULL THEN CAST(battery AS REAL)
    ELSE NULL
END
WHERE battery_pct IS NULL;

-- ============================================================
--  NODES — rename rssi column compat
-- ============================================================

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    last_rssi INTEGER;

UPDATE nodes
SET last_rssi = wifi_rssi
WHERE last_rssi IS NULL AND wifi_rssi IS NOT NULL;

-- ============================================================
--  EVENTS — align to V2 schema
-- ============================================================

-- Add message_id if missing (V1 used event_id)
ALTER TABLE events ADD COLUMN IF NOT EXISTS
    message_id TEXT;

-- Backfill message_id from event_id
UPDATE events
SET message_id = event_id
WHERE message_id IS NULL AND event_id IS NOT NULL;

-- Add ts_utc if missing (V1 used timestamp)
ALTER TABLE events ADD COLUMN IF NOT EXISTS
    ts_utc TEXT;

UPDATE events
SET ts_utc = timestamp
WHERE ts_utc IS NULL AND timestamp IS NOT NULL;

-- Add body_json if missing (V1 used data_json)
ALTER TABLE events ADD COLUMN IF NOT EXISTS
    body_json TEXT NOT NULL DEFAULT '{}';

UPDATE events
SET body_json = COALESCE(data_json, '{}')
WHERE body_json = '{}' AND data_json IS NOT NULL;

-- Add requires_ack
ALTER TABLE events ADD COLUMN IF NOT EXISTS
    requires_ack INTEGER NOT NULL DEFAULT 0;

-- ============================================================
--  ERRORS — V2 severity+domain model
-- ============================================================

-- Add V2 fields with LEGACY defaults
ALTER TABLE errors ADD COLUMN IF NOT EXISTS
    message_id TEXT;

UPDATE errors
SET message_id = 'legacy-' || CAST(id AS TEXT)
WHERE message_id IS NULL;

ALTER TABLE errors ADD COLUMN IF NOT EXISTS
    ts_utc TEXT;

UPDATE errors
SET ts_utc = COALESCE(received_at, strftime('%Y-%m-%dT%H:%M:%SZ','now'))
WHERE ts_utc IS NULL;

ALTER TABLE errors ADD COLUMN IF NOT EXISTS
    severity TEXT NOT NULL DEFAULT 'error';

ALTER TABLE errors ADD COLUMN IF NOT EXISTS
    domain TEXT NOT NULL DEFAULT 'LEGACY';

ALTER TABLE errors ADD COLUMN IF NOT EXISTS
    code TEXT;

UPDATE errors
SET code = COALESCE(error_code, 'UNKNOWN')
WHERE code IS NULL;

ALTER TABLE errors ADD COLUMN IF NOT EXISTS
    message TEXT;

UPDATE errors
SET message = COALESCE(error_msg, '')
WHERE message IS NULL;

ALTER TABLE errors ADD COLUMN IF NOT EXISTS
    diagnostics_json TEXT;

-- ============================================================
--  COMMANDS — align to V2 schema
-- ============================================================

ALTER TABLE commands ADD COLUMN IF NOT EXISTS
    arguments_json TEXT;

UPDATE commands
SET arguments_json = COALESCE(params_json, '{}')
WHERE arguments_json IS NULL;

ALTER TABLE commands ADD COLUMN IF NOT EXISTS
    issued_by TEXT NOT NULL DEFAULT 'system';

ALTER TABLE commands ADD COLUMN IF NOT EXISTS
    issued_ts_utc TEXT;

UPDATE commands
SET issued_ts_utc = COALESCE(issued_at, strftime('%Y-%m-%dT%H:%M:%SZ','now'))
WHERE issued_ts_utc IS NULL;

ALTER TABLE commands ADD COLUMN IF NOT EXISTS
    timeout_ms INTEGER NOT NULL DEFAULT 15000;

ALTER TABLE commands ADD COLUMN IF NOT EXISTS
    result_code TEXT;

ALTER TABLE commands ADD COLUMN IF NOT EXISTS
    result_details_json TEXT;

ALTER TABLE commands ADD COLUMN IF NOT EXISTS
    completed_ts_utc TEXT;

UPDATE commands
SET completed_ts_utc = ack_at
WHERE completed_ts_utc IS NULL AND ack_at IS NOT NULL;

UPDATE commands
SET result_code = CASE
    WHEN status = 'executed' THEN 'CMD_OK'
    WHEN status = 'failed'   THEN 'CMD_FAILED'
    WHEN status = 'rejected' THEN 'CMD_REJECTED'
    ELSE NULL
END
WHERE result_code IS NULL AND status IN ('executed', 'failed', 'rejected');

-- ============================================================
--  HEARTBEATS — add V2 fields
-- ============================================================

ALTER TABLE heartbeats ADD COLUMN IF NOT EXISTS
    free_heap_bytes INTEGER;

ALTER TABLE heartbeats ADD COLUMN IF NOT EXISTS
    queue_depth INTEGER NOT NULL DEFAULT 0;

ALTER TABLE heartbeats ADD COLUMN IF NOT EXISTS
    battery_pct REAL;

UPDATE heartbeats
SET battery_pct = CASE
    WHEN battery = -1 THEN NULL
    WHEN battery IS NOT NULL THEN CAST(battery AS REAL)
    ELSE NULL
END
WHERE battery_pct IS NULL;

-- ============================================================
--  ACKS — new table (V1 had none)
-- ============================================================

CREATE TABLE IF NOT EXISTS acks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id          TEXT    NOT NULL UNIQUE,
    node_id             TEXT    NOT NULL,
    ack_type            TEXT    NOT NULL,
    target_message_id   TEXT    NOT NULL,
    result              TEXT    NOT NULL,
    reason              TEXT,
    ts_utc              TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_acks_node     ON acks(node_id);
CREATE INDEX IF NOT EXISTS idx_acks_target   ON acks(target_message_id);

-- ============================================================
--  INDEX ADDITIONS for V2 query patterns
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_events_message_id  ON events(message_id);
CREATE INDEX IF NOT EXISTS idx_errors_message_id  ON errors(message_id);
CREATE INDEX IF NOT EXISTS idx_nodes_last_seen_utc ON nodes(last_seen_utc);
CREATE INDEX IF NOT EXISTS idx_nodes_status        ON nodes(status);

-- ============================================================
--  Re-enable FK enforcement
-- ============================================================

PRAGMA foreign_keys = ON;
