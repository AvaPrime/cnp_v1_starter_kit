from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import aiosqlite
from fastapi.testclient import TestClient

from app.main import create_app
from app.ops.anomalies import OpsService


async def seed_full_flow(db_path: str):
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
            ts = f"2026-03-18T10:0{idx}:00Z"
            await db.execute(
                """
                INSERT INTO heartbeats(message_id, node_id, ts_utc, status, wifi_rssi, battery_pct, free_heap_bytes, queue_depth, dead_letter_count, body_json)
                VALUES (?, 'node-1', ?, 'online', -75, 90, ?, ?, 0, ?)
                """,
                (
                    f"hb-{idx}",
                    ts,
                    1300 - idx * 50,
                    q,
                    json.dumps({"queue_depth": q, "free_heap_bytes": 1300 - idx * 50, "wifi_rssi": -75}),
                ),
            )
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        await db.execute(
            """
            INSERT INTO commands(command_id, node_id, command_type, category, issued_by, issued_ts_utc, status, timeout_ms, arguments_json, completed_ts_utc)
            VALUES ('cmd-1', 'node-1', 'set_relay', 'control', 'tester', ?, 'timeout', 1000, '{}', ?)
            """,
            (old_ts, old_ts),
        )
        await db.commit()


def test_e2e_detect_ack_resolve_cancel(db_path: str):
    app = create_app(db_path=db_path, enable_bridge=False)
    with TestClient(app) as client:
        import asyncio
        asyncio.run(seed_full_flow(db_path))
        service = OpsService()
        anomalies, actions, score = asyncio.run(service.analyze_node(db_path, "node-1", auto_heal=True))
        assert anomalies
        anomaly_id = anomalies[0].anomaly_id

        ack = client.post(f"/api/ops/anomalies/{anomaly_id}/acknowledge", json={"note": "ack"})
        assert ack.status_code == 200
        resolved = client.post(f"/api/ops/anomalies/{anomaly_id}/resolve", json={"note": "resolved"})
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "resolved"

        anomalies_listing = client.get("/api/ops/anomalies")
        assert anomalies_listing.status_code == 200
        action_id = actions[0].action_id
        cancelled = client.post(f"/api/ops/reflex/actions/{action_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["execution_status"] == "cancelled"

        fleet_score = client.get("/api/ops/fleet/score")
        assert fleet_score.status_code == 200
        assert fleet_score.json()["scope_type"] == "fleet"
