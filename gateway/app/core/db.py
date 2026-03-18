"""
gateway/app/core/db.py
──────────────────────
SQLite connection management for the CNP Gateway.

Changes from audit (P0-03 / P0-04):
  - All connections now enable WAL journal mode + busy_timeout to eliminate
    the 100% ReadTimeout failure on /api/nodes under concurrent load.
  - db_connect() is the single canonical way to open a connection —
    use it everywhere instead of bare aiosqlite.connect().
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aiosqlite

log = logging.getLogger("cnp.db")

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
  node_secret_hash TEXT,
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

-- Indexes added in audit Phase 0 for query performance
CREATE INDEX IF NOT EXISTS idx_events_priority_ts
  ON events(priority, ts_utc DESC);

CREATE INDEX IF NOT EXISTS idx_commands_node_status
  ON commands(node_id, status);

CREATE INDEX IF NOT EXISTS idx_nodes_status
  ON nodes(status);
"""

# ---------------------------------------------------------------------------
# Core connection helper — USE THIS EVERYWHERE instead of aiosqlite.connect()
# ---------------------------------------------------------------------------

@asynccontextmanager
async def db_connect(path: str) -> AsyncGenerator[aiosqlite.Connection, None]:
    """
    Async context manager that opens an aiosqlite connection with production
    pragmas applied:
      - WAL journal mode:  readers never block writers; eliminates the
                           100% ReadTimeout failure on concurrent /api/nodes.
      - busy_timeout 5s:   SQLite waits up to 5 seconds for a lock instead
                           of returning SQLITE_BUSY immediately. Under normal
                           load this is never hit; it prevents cascading errors
                           during brief write spikes.
      - synchronous NORMAL: safe with WAL; durability trade-off acceptable for
                           IoT telemetry (gateway can replay from nodes on crash).
    """
    db = await aiosqlite.connect(path)
    try:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("PRAGMA synchronous=NORMAL")
        db.row_factory = aiosqlite.Row
        yield db
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

async def init_db(path: str) -> None:
    """Initialise schema and apply all pragmas. Called once at lifespan start."""
    async with db_connect(path) as db:
        await db.executescript(SCHEMA_SQL)
        async with db.execute("PRAGMA table_info(nodes)") as cur:
            cols = [r["name"] for r in await cur.fetchall()]
        if "node_secret_hash" not in cols:
            await db.execute("ALTER TABLE nodes ADD COLUMN node_secret_hash TEXT")
        await db.commit()
    log.info("db.init_ok path=%s", path)
