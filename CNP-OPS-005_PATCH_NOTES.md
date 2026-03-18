# CNP-OPS-005 — Patch Notes & Integration Guide

**Document No.:** CNP-OPS-005  
**Status:** Implementation patch set  
**Applies to:** CNP-BOARD-003 Phase 2 exit (Sprint 4 complete)  

---

## Files in this patch set

```
migrations/
  002_ops_tables.sql              5 new ops tables + all indexes

gateway/app/ops/
  __init__.py                     OpsServices container + init_ops_db()
  models.py                       Pydantic DTOs, enums, HeartbeatSnapshot
  rules.py                        YAML catalog loader + rule registry
  catalog/rules.yaml              A-001 through A-010 rule definitions
  detector.py                     DetectorService — A-001/002/003/005/010
  scoring.py                      NodeScorer + fleet score aggregation
  healer.py                       HealerService — L0/L1/L2 reflex actions
  summaries.py                    SummaryService — daily heartbeat rollup
  db.py                           Async DB helpers for all ops tables
  api.py                          FastAPI router — /api/ops/* endpoints

gateway/tests/
  test_anomaly_rules.py           34 unit tests — rule triggers + suppression
  test_scoring.py                 28 unit tests — score math + ordering
  test_summaries.py               15 unit tests — aggregation + service lifecycle
```

---

## Prerequisites

Before applying this patch, confirm:

- [x] Board Phase 2 complete (Sprint 4 exit gates met)
- [x] `heartbeats` table has `free_heap_bytes`, `queue_depth` columns  
  (added in P1-08 / V2 schema — verify with `PRAGMA table_info(heartbeats)`)
- [x] `nodes` table has `offline_after_sec`, `last_seen_utc` columns  
  (V2 schema — present in `db.py` SCHEMA_SQL)
- [x] `pytest-asyncio>=0.23` in requirements.txt (P1-10 fix)
- [x] `pyyaml` added to requirements.txt (new dependency for rule loader)

Add to `gateway/requirements.txt`:
```
pyyaml>=6.0
```

---

## Step 1 — Apply the migration

```bash
cd gateway
python -c "
import asyncio
from app.ops import init_ops_db
from app.core.config import settings
asyncio.run(init_ops_db(settings.gateway_db_path))
"
```

Verify:
```bash
sqlite3 $GATEWAY_DB_PATH ".tables" | grep ops
# Expected: ops_anomalies  ops_health_scores  ops_reflex_actions  
#           ops_rule_state  heartbeat_daily_summary
```

---

## Step 2 — Wire OpsServices into main.py

Replace the existing `lifespan` in `gateway/app/main.py`:

```python
# gateway/app/main.py
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .api.routes import router
from .core.config import settings
from .core.db import init_db
from .core.mqtt_client import GatewayMqttBridge
from .core.registry import mark_offline_nodes
from .ops import OpsServices, init_ops_db
from .ops.api import router as ops_router

bridge = GatewayMqttBridge(settings.gateway_db_path)
ops = OpsServices(db_path=settings.gateway_db_path)


async def offline_watcher() -> None:
    while True:
        count = await mark_offline_nodes(
            settings.gateway_db_path, settings.offline_after_seconds
        )
        if count > 0:
            # Notify the detector about offline transitions
            # (zone info requires a nodes table join — extend as needed)
            pass
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app):
    await init_db(settings.gateway_db_path)
    await init_ops_db(settings.gateway_db_path)
    await bridge.start()
    ops.wire_bridge(bridge)
    bridge.set_ops_detector(ops.detector)   # see Step 3
    ops_tasks = await ops.start()
    watcher_task = asyncio.create_task(offline_watcher())
    try:
        yield
    finally:
        watcher_task.cancel()
        await ops.stop(ops_tasks)
        await bridge.stop()


app = FastAPI(title="CNP v1 Gateway", version="0.2.0", lifespan=lifespan)
app.include_router(router, prefix="/api")
app.include_router(ops_router, prefix="/api/ops")
```

---

## Step 3 — Wire detector into MQTT bridge

Add `set_ops_detector()` to `GatewayMqttBridge` in
`gateway/app/core/mqtt_client.py`:

```python
# In GatewayMqttBridge.__init__:
self._ops_detector = None

# New method:
def set_ops_detector(self, detector) -> None:
    self._ops_detector = detector

# In GatewayMqttBridge._handle(), after the heartbeat branch:
elif msg_type == "heartbeat":
    await update_heartbeat(self.db_path, envelope)
    if self._ops_detector:
        await self._ops_detector.on_heartbeat(envelope)   # ← add this line
```

---

## Step 4 — Wire offline transitions into detector

In `main.py`'s `offline_watcher`, after `mark_offline_nodes()` returns,
notify the detector for each newly-offline node:

```python
# Extended offline_watcher
async def offline_watcher() -> None:
    while True:
        # mark_offline_nodes returns count — extend to return node list
        # (or query nodes WHERE status changed in last 15s)
        await asyncio.sleep(15)
```

Full implementation deferred to P3-07 (per-node offline detection hardening),
which adds `fleet_event` records on transition. The detector's
`on_node_offline()` method is ready to receive these.

---

## Step 5 — Run the test suite

```bash
cd gateway
pytest tests/test_anomaly_rules.py tests/test_scoring.py tests/test_summaries.py \
  -v --cov=app/ops --cov-report=term-missing
```

Expected: 77 tests, all pass.  
Ops module coverage target: ≥ 75% for this phase.

---

## Enabled rules at Phase O2

| Rule | Status | Requires |
|---|---|---|
| A-001 Queue Congestion | **Enabled** | queue_depth in heartbeat |
| A-002 Memory Leak | **Enabled** | free_heap_bytes in heartbeat |
| A-003 Weak Connectivity | **Enabled** | wifi_rssi in heartbeat |
| A-004 Command Lag | Disabled | P3-05 command timeout reconciliation |
| A-005 Offline Flapping | **Enabled** | offline_watcher transitions |
| A-006 Auth Failure Burst | Disabled | P1-07 event log |
| A-007 Invalid Message Storm | Disabled | P1-05 rate-limit event log |
| A-008 Dead-Letter Growth | Disabled | P3-06 firmware retry semantics |
| A-009 Duplicate Spike | Disabled | P3-04 dedup instrumentation |
| A-010 Fleet Hotspot | **Enabled** | Active zone anomaly counts |

Enable additional rules by setting `enabled: true` in
`gateway/app/ops/catalog/rules.yaml` once their signal sources
are live.

---

## Reflex safety policy

Default: auto-execute L0, L1, L2. Require human for L3, L4.

To allow L3 auto-execution in a specific deployment (e.g., lab only):

```python
# gateway/app/ops/healer.py
AUTO_EXECUTE_MAX_LEVEL = SafetyLevel.L3
```

This is a code-level change by design — not a runtime config flag.
Unsafe automation must require a deliberate deploy.

---

## New API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/ops/anomalies` | List anomalies (filter by status, node) |
| GET | `/api/ops/anomalies/{id}` | Anomaly detail |
| POST | `/api/ops/anomalies/{id}/acknowledge` | Operator acknowledge |
| POST | `/api/ops/anomalies/{id}/resolve` | Mark resolved |
| GET | `/api/ops/fleet/score` | Recompute + return fleet score |
| GET | `/api/ops/nodes/{id}/score` | Recompute + return node score |
| GET | `/api/ops/fleet/health` | Cached per-node scores + anomaly counts |
| POST | `/api/ops/reflex/rules/{id}/simulate` | Dry-run a rule against evidence |
| POST | `/api/ops/reflex/actions/{id}/cancel` | Cancel pending reflex |

---

## Deferred to Phase O3

- `quarantine_node` reflex (requires P2-02 per-node auth)
- `request_reboot` reflex (requires L3 allowlist policy + P3-01 NTP)
- `pause_zone_automation` reflex (requires zone automation table)
- `require_human_approval` workflow (requires operator UI)
- A-006, A-007 security rules (require P1-05, P1-07 event streams)
- A-008, A-009 reliability rules (require P3-04, P3-06)
- Zone-level health scoring (requires stable metadata_json.zone population)
- Score retention trim job (7-day rolling window)

---

*CNP-OPS-005 · Codessa Systems · March 2026*
