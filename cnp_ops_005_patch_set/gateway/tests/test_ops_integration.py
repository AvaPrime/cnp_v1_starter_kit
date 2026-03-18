from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from app.core.db import apply_sql_file, init_db
from app.main import create_app
from app.ops.anomalies import OpsService


async def seed_node_and_heartbeats(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO nodes(
                node_id, device_uid, node_name, node_type, protocol_version, firmware_version,
                hardware_model, capabilities_json, status, first_seen_utc, last_seen_utc, metadata_json
            ) VALUES ('node-1', 'dev-1', 'Node 1', 'sensor', 'CNPv1', '1.0.0', 'esp32-c3', '{}', 'online', '2026-03-18T10:00:00Z', '2026-03-18T10:03:00Z', ?)
            """,
            (json.dumps({"zone": "lab"}),),
        )
        for idx, q in enumerate([11, 12, 13], start=1):
            await db.execute(
                """
                INSERT INTO heartbeats(message_id, node_id, ts_utc, status, wifi_rssi, battery_pct, free_heap_bytes, queue_depth, dead_letter_count, body_json)
                VALUES (?, 'node-1', ?, 'online', -82, 90, ?, ?, 0, ?)
                """,
                (
                    f"hb-{idx}",
                    f"2026-03-18T10:0{idx}:00Z",
                    1200 - idx * 100,
                    q,
                    json.dumps({"queue_depth": q, "free_heap_bytes": 1200 - idx * 100, "wifi_rssi": -82}),
                ),
            )
        await db.commit()


@pytest.mark.asyncio
async def test_ops_routes_and_simulation(initialized_db: str):
    await seed_node_and_heartbeats(initialized_db)
    service = OpsService()
    anomalies, actions, score = await service.analyze_node(initialized_db, "node-1", auto_heal=True)
    assert anomalies
    app = create_app(db_path=initialized_db, enable_bridge=False)
    with TestClient(app) as client:
        response = client.get("/api/ops/anomalies")
        assert response.status_code == 200
        body = response.json()
        assert len(body) >= 1

        anomaly_id = body[0]["anomaly_id"]
        ack = client.post(f"/api/ops/anomalies/{anomaly_id}/acknowledge", json={"note": "investigating"})
        assert ack.status_code == 200
        assert ack.json()["status"] == "acknowledged"

        score_response = client.get("/api/ops/nodes/node-1/score")
        assert score_response.status_code == 200
        assert score_response.json()["scope_id"] == "node-1"

        sim = client.post("/api/ops/reflex/rules/A-001/simulate", json={"node_id": "node-1"})
        assert sim.status_code == 200
        assert sim.json()["planned_action"] == "publish_config_update"


@pytest.mark.asyncio
async def test_fleet_health_returns_daily_summary(initialized_db: str):
    await seed_node_and_heartbeats(initialized_db)
    service = OpsService()
    await service.analyze_node(initialized_db, "node-1", auto_heal=False)
    app = create_app(db_path=initialized_db, enable_bridge=False)
    with TestClient(app) as client:
        response = client.get("/api/ops/fleet/health")
        assert response.status_code == 200
        data = response.json()
        assert data
        assert data[0]["node_id"] == "node-1"
