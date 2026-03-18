# db/migrations — SQL Migration Files

This directory contains the database migration history for the CNP Gateway.

## How the gateway uses these files

The production gateway (`gateway/app/core/db.py:init_db()`) manages schema creation directly via the embedded `SCHEMA_SQL` constant — it does **not** execute these files at startup. They exist as:

1. **Reference** — authoritative record of schema evolution
2. **Manual administration** — apply to an existing DB with `sqlite3 cnp_gateway.db < 0005_per_node_secrets.sql`
3. **Future migration tooling** — Phase 3 will introduce Alembic or a custom runner

## Migration history

| File | Description | Applied in |
|---|---|---|
| `0001_baseline_schema.sql` | Initial schema — nodes, events, commands, errors, acks | v0.1.0 |
| `0002_v2_views_and_trim.sql` | Analytics views, trim procedures | v0.2.0 |
| `0003_ops_tables.sql` | OPS-004 tables — anomalies, fleet scores, heartbeats | v0.2.0 (ops layer) |
| `0004_v1_to_v2_schema.sql` | Schema migration from v0.1 to v0.2 field names | v0.2.0 |
| `0005_per_node_secrets.sql` | `node_secret_hash` column on nodes table | v0.2.0 |

## Applying a migration manually

```bash
# Apply a single migration to an existing database
sqlite3 /path/to/cnp_gateway.db < db/migrations/0005_per_node_secrets.sql

# Check current schema
sqlite3 cnp_gateway.db ".schema nodes"

# Verify node_secret_hash column exists
sqlite3 cnp_gateway.db "PRAGMA table_info(nodes);" | grep secret
```

## Adding a new migration

1. Create `db/migrations/NNNN_description.sql` (zero-padded sequence number)
2. Write idempotent SQL — use `IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, etc.
3. Test against a fresh DB and against an existing production DB
4. Document it in this README table
5. Update `gateway/app/core/db.py:SCHEMA_SQL` if the change is required at startup for new installs
