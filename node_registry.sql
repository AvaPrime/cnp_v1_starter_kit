-- ============================================================
--  Codessa Node Protocol v1 — Node Registry Schema (SQLite)
-- ============================================================
-- Usage:
--   sqlite3 codessa_registry.db < node_registry.sql
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
--  NODES — one row per registered physical node
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nodes (
    node_id           TEXT    PRIMARY KEY,          -- e.g. cnp-office-temp-01
    node_name         TEXT    NOT NULL,
    node_type         TEXT    NOT NULL CHECK(node_type IN ('sensor','actuator','hybrid','gateway')),
    zone              TEXT    NOT NULL DEFAULT 'unassigned',
    protocol_version  TEXT    NOT NULL DEFAULT 'CNPv1',
    firmware_version  TEXT,
    capabilities_json TEXT,                         -- JSON blob from hello payload
    status            TEXT    NOT NULL DEFAULT 'offline' CHECK(status IN ('online','offline','degraded')),
    battery           REAL,                         -- 0–100 or NULL if wired
    wifi_rssi         INTEGER,
    uptime_sec        INTEGER DEFAULT 0,
    last_seen         TEXT,                         -- ISO-8601 UTC
    registered_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    notes             TEXT
);

-- ------------------------------------------------------------
--  EVENTS — append-only log of meaningful things that happened
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT    UNIQUE NOT NULL,            -- e.g. evt-000001
    node_id     TEXT    NOT NULL REFERENCES nodes(node_id),
    event_type  TEXT    NOT NULL,                  -- e.g. temperature_reading
    category    TEXT    NOT NULL CHECK(category IN ('telemetry','alert','interaction','system','security','power')),
    priority    TEXT    NOT NULL DEFAULT 'normal' CHECK(priority IN ('low','normal','high','critical')),
    data_json   TEXT,                              -- event payload
    timestamp   TEXT    NOT NULL,                  -- ISO-8601 from node
    received_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ------------------------------------------------------------
--  COMMANDS — every command issued and its result
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS commands (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id   TEXT    UNIQUE NOT NULL,
    node_id      TEXT    NOT NULL REFERENCES nodes(node_id),
    command_type TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    params_json  TEXT,
    status       TEXT    NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','executed','failed','rejected','queued','timeout')),
    issued_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    ack_at       TEXT,
    detail       TEXT
);

-- ------------------------------------------------------------
--  HEARTBEATS — lightweight alive-check log (recent only)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS heartbeats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id    TEXT    NOT NULL REFERENCES nodes(node_id),
    status     TEXT    NOT NULL,
    uptime_sec INTEGER,
    battery    REAL,
    wifi_rssi  INTEGER,
    received_at TEXT   NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Keep only the last 500 heartbeats per node to prevent unbounded growth
CREATE TRIGGER IF NOT EXISTS trim_heartbeats
AFTER INSERT ON heartbeats
BEGIN
    DELETE FROM heartbeats
    WHERE node_id = NEW.node_id
      AND id NOT IN (
          SELECT id FROM heartbeats
          WHERE node_id = NEW.node_id
          ORDER BY id DESC
          LIMIT 500
      );
END;

-- ------------------------------------------------------------
--  ERRORS — node-reported errors
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     TEXT NOT NULL REFERENCES nodes(node_id),
    error_code  TEXT NOT NULL,
    error_msg   TEXT,
    recoverable INTEGER DEFAULT 1,  -- 0=false, 1=true
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ------------------------------------------------------------
--  CONFIG — per-node configuration pushed from gateway
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS node_config (
    node_id                 TEXT PRIMARY KEY REFERENCES nodes(node_id),
    heartbeat_interval_sec  INTEGER NOT NULL DEFAULT 30,
    report_interval_sec     INTEGER NOT NULL DEFAULT 60,
    permissions_json        TEXT,   -- allowed command types
    custom_json             TEXT,   -- any extra config
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ------------------------------------------------------------
--  INDEXES
-- ------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_events_node      ON events(node_id);
CREATE INDEX IF NOT EXISTS idx_events_category  ON events(category);
CREATE INDEX IF NOT EXISTS idx_events_priority  ON events(priority);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_commands_node    ON commands(node_id);
CREATE INDEX IF NOT EXISTS idx_commands_status  ON commands(status);
CREATE INDEX IF NOT EXISTS idx_heartbeats_node  ON heartbeats(node_id);

-- ------------------------------------------------------------
--  VIEWS — handy queries for the gateway / dashboard
-- ------------------------------------------------------------

-- Current live status of all nodes
CREATE VIEW IF NOT EXISTS v_node_status AS
SELECT
    n.node_id,
    n.node_name,
    n.node_type,
    n.zone,
    n.status,
    n.battery,
    n.wifi_rssi,
    n.last_seen,
    CAST((julianday('now') - julianday(n.last_seen)) * 86400 AS INTEGER) AS seconds_since_seen,
    n.firmware_version
FROM nodes n;

-- Recent high-priority events (last 24 hours)
CREATE VIEW IF NOT EXISTS v_recent_alerts AS
SELECT
    e.event_id,
    e.node_id,
    n.node_name,
    n.zone,
    e.event_type,
    e.priority,
    e.data_json,
    e.timestamp
FROM events e
JOIN nodes n ON e.node_id = n.node_id
WHERE e.priority IN ('high','critical')
  AND e.timestamp >= datetime('now', '-24 hours')
ORDER BY e.timestamp DESC;

-- Pending commands
CREATE VIEW IF NOT EXISTS v_pending_commands AS
SELECT
    c.command_id,
    c.node_id,
    c.command_type,
    c.category,
    c.params_json,
    c.issued_at
FROM commands c
WHERE c.status = 'pending'
ORDER BY c.issued_at ASC;

-- Node event summary (last 24 hours)
CREATE VIEW IF NOT EXISTS v_event_summary AS
SELECT
    node_id,
    category,
    COUNT(*) AS event_count,
    MAX(timestamp) AS last_event
FROM events
WHERE timestamp >= datetime('now', '-24 hours')
GROUP BY node_id, category;
