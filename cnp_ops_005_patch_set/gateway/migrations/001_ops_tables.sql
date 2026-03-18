BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS ops_anomalies (
  anomaly_id TEXT PRIMARY KEY,
  detected_ts_utc TEXT NOT NULL,
  node_id TEXT,
  zone TEXT,
  anomaly_type TEXT NOT NULL,
  category TEXT NOT NULL,
  severity TEXT NOT NULL,
  score REAL NOT NULL,
  confidence REAL NOT NULL,
  status TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  recommended_action TEXT,
  source_rule_id TEXT NOT NULL,
  correlation_id TEXT,
  resolved_ts_utc TEXT
);

CREATE TABLE IF NOT EXISTS ops_reflex_actions (
  action_id TEXT PRIMARY KEY,
  anomaly_id TEXT NOT NULL,
  issued_ts_utc TEXT NOT NULL,
  node_id TEXT,
  action_type TEXT NOT NULL,
  action_payload_json TEXT NOT NULL,
  execution_status TEXT NOT NULL,
  result_json TEXT,
  safe_mode INTEGER NOT NULL DEFAULT 1,
  requires_human INTEGER NOT NULL DEFAULT 0,
  completed_ts_utc TEXT,
  FOREIGN KEY (anomaly_id) REFERENCES ops_anomalies(anomaly_id)
);

CREATE TABLE IF NOT EXISTS ops_health_scores (
  score_id TEXT PRIMARY KEY,
  ts_utc TEXT NOT NULL,
  scope_type TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  health_score REAL NOT NULL,
  reliability_score REAL NOT NULL,
  security_score REAL NOT NULL,
  performance_score REAL NOT NULL,
  maintainability_score REAL NOT NULL,
  responsiveness_score REAL NOT NULL DEFAULT 100,
  evidence_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ops_rule_state (
  rule_id TEXT NOT NULL,
  scope_type TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  last_triggered_ts_utc TEXT,
  suppression_until_ts_utc TEXT,
  consecutive_hits INTEGER NOT NULL DEFAULT 0,
  consecutive_recoveries INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (rule_id, scope_type, scope_id)
);

CREATE TABLE IF NOT EXISTS heartbeat_daily_summary (
  node_id TEXT NOT NULL,
  day_utc TEXT NOT NULL,
  min_free_heap_bytes INTEGER,
  max_free_heap_bytes INTEGER,
  avg_free_heap_bytes REAL,
  min_wifi_rssi INTEGER,
  max_wifi_rssi INTEGER,
  avg_wifi_rssi REAL,
  min_queue_depth INTEGER,
  max_queue_depth INTEGER,
  avg_queue_depth REAL,
  sample_count INTEGER NOT NULL,
  PRIMARY KEY (node_id, day_utc)
);

CREATE INDEX IF NOT EXISTS idx_ops_anomalies_node_status ON ops_anomalies(node_id, status);
CREATE INDEX IF NOT EXISTS idx_ops_reflex_actions_node_status ON ops_reflex_actions(node_id, execution_status);
CREATE INDEX IF NOT EXISTS idx_ops_health_scores_scope_ts ON ops_health_scores(scope_type, scope_id, ts_utc DESC);

COMMIT;
