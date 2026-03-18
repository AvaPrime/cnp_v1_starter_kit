-- ============================================================
--  CNP EPIC-02 — P2-02
--  Migration: 004_per_node_secrets.sql
--
--  Adds node_secret_hash column to nodes table.
--  Column is nullable:
--    NULL  → node uses bootstrap token (Stage 1)
--    TEXT  → node has per-node HMAC secret (Stage 2)
--
--  Applied after 003_v1_to_v2_schema.sql.
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
    node_secret_hash TEXT;

-- Index for fast secret lookup on every authenticated request
CREATE INDEX IF NOT EXISTS idx_nodes_secret_hash
    ON nodes(node_id)
    WHERE node_secret_hash IS NOT NULL;

-- Bootstrap rate limit tracking table
-- Records registration attempts per source to enforce
-- the 30/minute bootstrap cap (P1-07 spec)
CREATE TABLE IF NOT EXISTS bootstrap_rate_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_ip   TEXT    NOT NULL,
    ts_utc      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_bootstrap_rate_ip
    ON bootstrap_rate_log(source_ip, ts_utc);

-- Auto-trim: keep last 1000 entries per IP
CREATE TRIGGER IF NOT EXISTS trim_bootstrap_log
AFTER INSERT ON bootstrap_rate_log
BEGIN
    DELETE FROM bootstrap_rate_log
    WHERE source_ip = NEW.source_ip
      AND id NOT IN (
          SELECT id FROM bootstrap_rate_log
          WHERE source_ip = NEW.source_ip
          ORDER BY id DESC
          LIMIT 1000
      );
END;
