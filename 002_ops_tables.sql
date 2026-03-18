-- ============================================================
--  CNP-OPS-004 — Operational Intelligence Layer
--  Migration: 002_ops_tables.sql
--
--  Run after 001 (base schema). Safe to re-run — all
--  statements use IF NOT EXISTS / OR IGNORE guards.
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
--  ops_anomalies
--  One row per detected anomaly. Status machine:
--    detected → active → acknowledged → resolved
--                      ↘ escalated    → resolved
--                      ↘ suppressed   → active
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_anomalies (
    anomaly_id          TEXT    PRIMARY KEY,
    detected_ts_utc     TEXT    NOT NULL,
    node_id             TEXT    REFERENCES nodes(node_id),
    zone                TEXT,
    anomaly_type        TEXT    NOT NULL,
    category            TEXT    NOT NULL
        CHECK(category IN ('reliability','performance','security','connectivity','fleet')),
    severity            TEXT    NOT NULL
        CHECK(severity IN ('info','warning','error','critical')),
    score               REAL    NOT NULL CHECK(score BETWEEN 0 AND 1),
    confidence          REAL    NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    status              TEXT    NOT NULL DEFAULT 'detected'
        CHECK(status IN ('detected','active','acknowledged','suppressed','escalated','resolved')),
    evidence_json       TEXT    NOT NULL DEFAULT '{}',
    recommended_action  TEXT,
    source_rule_id      TEXT    NOT NULL,
    correlation_id      TEXT,
    acknowledged_by     TEXT,
    acknowledged_ts_utc TEXT,
    resolved_ts_utc     TEXT
);

CREATE INDEX IF NOT EXISTS idx_anomalies_node
    ON ops_anomalies(node_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_status
    ON ops_anomalies(status);
CREATE INDEX IF NOT EXISTS idx_anomalies_severity
    ON ops_anomalies(severity);
CREATE INDEX IF NOT EXISTS idx_anomalies_detected
    ON ops_anomalies(detected_ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_zone
    ON ops_anomalies(zone);
CREATE INDEX IF NOT EXISTS idx_anomalies_type
    ON ops_anomalies(anomaly_type);

-- ------------------------------------------------------------
--  ops_reflex_actions
--  Every action the reflex engine issued, its safety level,
--  execution result, and link back to the anomaly that caused it.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_reflex_actions (
    action_id           TEXT    PRIMARY KEY,
    anomaly_id          TEXT    NOT NULL REFERENCES ops_anomalies(anomaly_id),
    issued_ts_utc       TEXT    NOT NULL,
    node_id             TEXT    REFERENCES nodes(node_id),
    action_type         TEXT    NOT NULL,
    action_payload_json TEXT    NOT NULL DEFAULT '{}',
    safety_level        INTEGER NOT NULL DEFAULT 1
        CHECK(safety_level BETWEEN 0 AND 4),
    execution_status    TEXT    NOT NULL DEFAULT 'pending'
        CHECK(execution_status IN ('pending','executing','completed','failed','cancelled','superseded')),
    result_json         TEXT,
    safe_mode           INTEGER NOT NULL DEFAULT 1,
    requires_human      INTEGER NOT NULL DEFAULT 0,
    completed_ts_utc    TEXT
);

CREATE INDEX IF NOT EXISTS idx_reflex_anomaly
    ON ops_reflex_actions(anomaly_id);
CREATE INDEX IF NOT EXISTS idx_reflex_node
    ON ops_reflex_actions(node_id);
CREATE INDEX IF NOT EXISTS idx_reflex_status
    ON ops_reflex_actions(execution_status);
CREATE INDEX IF NOT EXISTS idx_reflex_issued
    ON ops_reflex_actions(issued_ts_utc DESC);

-- ------------------------------------------------------------
--  ops_health_scores
--  Time-series of computed health scores, per node/zone/fleet.
--  Retain last 7 days by default (application-level trim).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_health_scores (
    score_id                TEXT    PRIMARY KEY,
    ts_utc                  TEXT    NOT NULL,
    scope_type              TEXT    NOT NULL
        CHECK(scope_type IN ('node','zone','fleet')),
    scope_id                TEXT    NOT NULL,
    health_score            REAL    NOT NULL CHECK(health_score BETWEEN 0 AND 100),
    reliability_score       REAL    NOT NULL CHECK(reliability_score BETWEEN 0 AND 100),
    security_score          REAL    NOT NULL CHECK(security_score BETWEEN 0 AND 100),
    performance_score       REAL    NOT NULL CHECK(performance_score BETWEEN 0 AND 100),
    maintainability_score   REAL    NOT NULL CHECK(maintainability_score BETWEEN 0 AND 100),
    responsiveness_score    REAL    NOT NULL CHECK(responsiveness_score BETWEEN 0 AND 100),
    evidence_json           TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_scores_scope
    ON ops_health_scores(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_scores_ts
    ON ops_health_scores(ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_scores_scope_ts
    ON ops_health_scores(scope_type, scope_id, ts_utc DESC);

-- ------------------------------------------------------------
--  ops_rule_state
--  Per-rule, per-scope hit counters, suppression windows,
--  and recovery tracking. Hot path for the detector.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_rule_state (
    rule_id                     TEXT    NOT NULL,
    scope_type                  TEXT    NOT NULL,
    scope_id                    TEXT    NOT NULL,
    last_triggered_ts_utc       TEXT,
    suppression_until_ts_utc    TEXT,
    consecutive_hits            INTEGER NOT NULL DEFAULT 0,
    consecutive_recoveries      INTEGER NOT NULL DEFAULT 0,
    last_anomaly_id             TEXT    REFERENCES ops_anomalies(anomaly_id),
    PRIMARY KEY (rule_id, scope_type, scope_id)
);

CREATE INDEX IF NOT EXISTS idx_rule_state_scope
    ON ops_rule_state(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_rule_state_suppression
    ON ops_rule_state(suppression_until_ts_utc)
    WHERE suppression_until_ts_utc IS NOT NULL;

-- ------------------------------------------------------------
--  heartbeat_daily_summary
--  Pre-aggregated daily rollups. Populated by summaries.py
--  background task. Enables trend queries without scanning
--  the raw heartbeats table.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS heartbeat_daily_summary (
    node_id             TEXT    NOT NULL REFERENCES nodes(node_id),
    day_utc             TEXT    NOT NULL,   -- YYYY-MM-DD
    min_free_heap_bytes INTEGER,
    max_free_heap_bytes INTEGER,
    avg_free_heap_bytes REAL,
    min_wifi_rssi       INTEGER,
    max_wifi_rssi       INTEGER,
    avg_wifi_rssi       REAL,
    min_queue_depth     INTEGER,
    max_queue_depth     INTEGER,
    avg_queue_depth     REAL,
    offline_transitions INTEGER NOT NULL DEFAULT 0,
    heartbeat_count     INTEGER NOT NULL DEFAULT 0,
    sample_count        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (node_id, day_utc)
);

CREATE INDEX IF NOT EXISTS idx_hb_summary_day
    ON heartbeat_daily_summary(day_utc DESC);
CREATE INDEX IF NOT EXISTS idx_hb_summary_node
    ON heartbeat_daily_summary(node_id);
