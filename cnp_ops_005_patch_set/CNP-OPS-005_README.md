# CNP-OPS-005 Implementation Patch Set

This patch set extends the CNP v1 starter kit with the first production-ready implementation
slice of the Operational Intelligence Layer.

## Included

- SQLite migration: `gateway/migrations/001_ops_tables.sql`
- New ops package: `gateway/app/ops/`
- FastAPI routes:
  - `GET /api/ops/anomalies`
  - `GET /api/ops/anomalies/{anomaly_id}`
  - `POST /api/ops/anomalies/{anomaly_id}/acknowledge`
  - `POST /api/ops/anomalies/{anomaly_id}/resolve`
  - `GET /api/ops/fleet/score`
  - `GET /api/ops/nodes/{node_id}/score`
  - `GET /api/ops/fleet/health`
  - `POST /api/ops/reflex/rules/{rule_id}/simulate`
  - `POST /api/ops/reflex/actions/{action_id}/cancel`
- First five anomaly rules:
  - A-001 Queue Congestion
  - A-002 Memory Leak Suspected
  - A-003 Weak Connectivity
  - A-004 Command Lag
  - A-005 Offline Flapping
- Score calculator with persistence
- Unit, integration, and end-to-end tests

## Notes

- The reflex engine auto-executes only safe actions in this patch.
- MQTT runtime support remains available, but tests run with the bridge disabled.
- The implementation uses SQLite and is structured for later PostgreSQL adapter work.
