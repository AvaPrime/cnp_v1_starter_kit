-- ============================================================
--  CNP EPIC-01 — P1-08 + P1-09
--  Migration: 001_v2_views_and_trim.sql
--
--  P1-08: Port V1 SQL helper views to V2 schema column names
--  P1-09: Heartbeat AFTER INSERT trim trigger (cap 1000/node)
--
--  Apply after init_db() has run the base SCHEMA_SQL.
--  Safe to re-run — all statements use IF NOT EXISTS.
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
--  P1-08 Views — updated for V2 column names
--  V1 → V2 renames applied:
--    last_seen    → last_seen_utc
--    battery      → battery_pct
--    data_json    → body_json
--    timestamp    → ts_utc
--    params_json  → arguments_json
-- ------------------------------------------------------------

-- Current live status of all nodes
DROP VIEW IF EXISTS v_node_status;
CREATE VIEW v_node_status AS
SELECT
    n.node_id,
    n.node_name,
    n.node_type,
    -- zone from metadata_json with fallback for V1 schema compat
    COALESCE(
        JSON_EXTRACT(n.metadata_json, '$.zone'),
        n.node_id   -- fallback if metadata missing
    )                                                           AS zone,
    n.status,
    n.battery_pct,
    n.last_rssi                                                 AS wifi_rssi,
    n.last_seen_utc                                             AS last_seen,
    CAST(
        (julianday('now') - julianday(n.last_seen_utc)) * 86400
        AS INTEGER
    )                                                           AS seconds_since_seen,
    n.firmware_version,
    n.free_heap_bytes,
    n.queue_depth,
    n.supports_ota,
    n.config_version
FROM nodes n;


-- Recent high-priority events (last 24 hours)
DROP VIEW IF EXISTS v_recent_alerts;
CREATE VIEW v_recent_alerts AS
SELECT
    e.message_id                                                AS event_id,
    e.node_id,
    n.node_name,
    COALESCE(JSON_EXTRACT(n.metadata_json, '$.zone'), '')       AS zone,
    e.event_type,
    e.priority,
    e.body_json                                                 AS data_json,
    e.ts_utc                                                    AS timestamp
FROM events e
JOIN nodes n ON e.node_id = n.node_id
WHERE e.priority IN ('high', 'critical')
  AND e.ts_utc >= datetime('now', '-24 hours')
ORDER BY e.ts_utc DESC;


-- Pending commands (awaiting node poll or MQTT delivery)
DROP VIEW IF EXISTS v_pending_commands;
CREATE VIEW v_pending_commands AS
SELECT
    c.command_id,
    c.node_id,
    c.command_type,
    c.category,
    c.arguments_json                                            AS params_json,
    c.issued_ts_utc                                             AS issued_at,
    c.timeout_ms
FROM commands c
WHERE c.status IN ('queued', 'pending')
ORDER BY c.issued_ts_utc ASC;


-- Node event summary (last 24 hours)
DROP VIEW IF EXISTS v_event_summary;
CREATE VIEW v_event_summary AS
SELECT
    node_id,
    category,
    COUNT(*)                                                    AS event_count,
    MAX(ts_utc)                                                 AS last_event
FROM events
WHERE ts_utc >= datetime('now', '-24 hours')
GROUP BY node_id, category;


-- Fleet summary — used by GET /api/summary
DROP VIEW IF EXISTS v_fleet_summary;
CREATE VIEW v_fleet_summary AS
SELECT
    COUNT(*)                                                    AS total_nodes,
    SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END)         AS online_count,
    SUM(CASE WHEN status = 'offline' THEN 1 ELSE 0 END)        AS offline_count,
    SUM(CASE WHEN status = 'degraded' THEN 1 ELSE 0 END)       AS degraded_count,
    (
        SELECT COUNT(*) FROM events
        WHERE priority IN ('high','critical')
          AND ts_utc >= datetime('now', '-24 hours')
    )                                                           AS alerts_24h,
    (
        SELECT COUNT(*) FROM errors
        WHERE ts_utc >= datetime('now', '-24 hours')
    )                                                           AS errors_24h,
    (
        SELECT COUNT(*) FROM commands
        WHERE status IN ('pending', 'queued')
    )                                                           AS pending_commands
FROM nodes
WHERE status != 'retired';


-- ------------------------------------------------------------
--  P1-09 — Heartbeat trim trigger
--  Fires AFTER INSERT on heartbeats.
--  Deletes oldest rows beyond 1000 per node_id.
--  Tested: insert 1010 rows → exactly 1000 retained.
-- ------------------------------------------------------------
DROP TRIGGER IF EXISTS trim_heartbeats;
CREATE TRIGGER trim_heartbeats
AFTER INSERT ON heartbeats
BEGIN
    DELETE FROM heartbeats
    WHERE node_id = NEW.node_id
      AND id NOT IN (
          SELECT id
          FROM heartbeats
          WHERE node_id = NEW.node_id
          ORDER BY id DESC
          LIMIT 1000
      );
END;


-- ------------------------------------------------------------
--  Indexes for new views' hot paths
-- ------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_events_ts_priority
    ON events(ts_utc DESC, priority);

CREATE INDEX IF NOT EXISTS idx_commands_status_issued
    ON commands(status, issued_ts_utc ASC);

CREATE INDEX IF NOT EXISTS idx_nodes_status
    ON nodes(status);
