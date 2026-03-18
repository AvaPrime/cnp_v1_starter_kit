from __future__ import annotations

import pytest

from conftest import auth_headers, make_hello_envelope, seed_node


@pytest.mark.asyncio
async def test_nodes_valid_status_filter_returns_200(app_client, db_path):
    await seed_node(db_path, "cnp-filter-01")
    response = await app_client.get("/api/nodes?status=online")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_status",
    [
        "'; DROP TABLE nodes; --",
        "online OR 1=1",
        "ONLINE",
        "active",
        "up",
        "1",
        "",
        "online--",
        "online /*",
    ],
)
async def test_nodes_invalid_status_returns_400(app_client, bad_status):
    response = await app_client.get(f"/api/nodes?status={bad_status}")
    if bad_status == "":
        assert response.status_code == 200
        return
    assert response.status_code == 400
    payload = response.json()
    assert "error" in payload
    assert payload["error"]["code"] == "invalid_filter"
    assert "online" in payload["error"]["message"]


@pytest.mark.asyncio
async def test_nodes_all_valid_statuses_accepted(app_client):
    for status in ("online", "offline", "degraded", "unknown", "retired"):
        response = await app_client.get(f"/api/nodes?status={status}")
        assert response.status_code == 200, f"Status '{status}' unexpectedly rejected"


@pytest.mark.asyncio
async def test_events_valid_priority_filter_returns_200(app_client):
    response = await app_client.get("/api/events?priority=high")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_priority",
    [
        "HIGH",
        "CRITICAL",
        "'; SELECT * FROM nodes; --",
        "high OR 1=1",
        "urgent",
        "p1",
    ],
)
async def test_events_invalid_priority_returns_400(app_client, bad_priority):
    response = await app_client.get(f"/api/events?priority={bad_priority}")
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "invalid_filter"


@pytest.mark.asyncio
async def test_events_all_valid_priorities_accepted(app_client):
    for priority in ("low", "normal", "high", "critical"):
        response = await app_client.get(f"/api/events?priority={priority}")
        assert response.status_code == 200, f"Priority '{priority}' unexpectedly rejected"


@pytest.mark.asyncio
async def test_list_nodes_does_not_expose_secret_hash(app_client, db_path):
    response = await app_client.post(
        "/api/node/hello",
        headers=auth_headers(),
        json=make_hello_envelope("cnp-secret-01"),
    )
    assert response.status_code == 200

    nodes_resp = await app_client.get("/api/nodes")
    assert nodes_resp.status_code == 200

    for node in nodes_resp.json():
        assert "node_secret_hash" not in node
        assert "secret" not in node


@pytest.mark.asyncio
async def test_get_node_does_not_expose_secret_hash(app_client, db_path):
    await app_client.post(
        "/api/node/hello",
        headers=auth_headers(),
        json=make_hello_envelope("cnp-secret-02"),
    )

    resp = await app_client.get("/api/nodes/cnp-secret-02")
    assert resp.status_code == 200
    node = resp.json()
    assert "node_secret_hash" not in node
    assert "secret" not in node


@pytest.mark.asyncio
async def test_config_patch_valid_payload_returns_ok(app_client, db_path):
    await seed_node(db_path, "cnp-cfg-01")
    response = await app_client.patch(
        "/api/nodes/cnp-cfg-01/config",
        json={"heartbeat_interval_sec": 30, "report_interval_sec": 60},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_payload,expected_code",
    [
        ({"heartbeat_interval_sec": -1}, "invalid_config"),
        ({"heartbeat_interval_sec": 0}, "invalid_config"),
        ({"heartbeat_interval_sec": 9}, "invalid_config"),
        ({"heartbeat_interval_sec": 3601}, "invalid_config"),
        ({"report_interval_sec": -5}, "invalid_config"),
        ({"unknown_field": "injected"}, "invalid_config"),
        ({"heartbeat_interval_sec": 30, "sql_injection": "'; DROP TABLE nodes; --"}, "invalid_config"),
    ],
)
async def test_config_patch_rejects_invalid_payload(app_client, db_path, bad_payload, expected_code):
    await seed_node(db_path, "cnp-cfg-bad-01")
    response = await app_client.patch("/api/nodes/cnp-cfg-bad-01/config", json=bad_payload)
    assert response.status_code == 400
    payload = response.json()
    assert "error" in payload
    assert payload["error"]["code"] == expected_code, (
        f"Expected '{expected_code}' but got '{payload['error']['code']}' for payload {bad_payload}"
    )


@pytest.mark.asyncio
async def test_config_patch_boundary_values_accepted(app_client, db_path):
    await seed_node(db_path, "cnp-cfg-bound-01")
    for hb, rep in [(10, 10), (3600, 3600), (10, 3600)]:
        response = await app_client.patch(
            "/api/nodes/cnp-cfg-bound-01/config",
            json={"heartbeat_interval_sec": hb, "report_interval_sec": rep},
        )
        assert response.status_code == 200, f"Boundary ({hb}, {rep}) was unexpectedly rejected"


@pytest.mark.asyncio
async def test_config_patch_missing_node_returns_404(app_client):
    response = await app_client.patch(
        "/api/nodes/does-not-exist-01/config",
        json={"heartbeat_interval_sec": 30},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "node_not_found"


@pytest.mark.asyncio
async def test_config_patch_invalid_json_returns_400(app_client, db_path):
    await seed_node(db_path, "cnp-cfg-json-01")
    response = await app_client.patch(
        "/api/nodes/cnp-cfg-json-01/config",
        content="{ not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_json"


@pytest.mark.asyncio
async def test_config_patch_persists_to_db(app_client, db_path):
    import aiosqlite

    await seed_node(db_path, "cnp-cfg-persist-01")

    await app_client.patch(
        "/api/nodes/cnp-cfg-persist-01/config",
        json={"heartbeat_interval_sec": 45, "report_interval_sec": 90},
    )

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT heartbeat_interval_sec, report_interval_sec FROM node_config WHERE node_id=?",
            ("cnp-cfg-persist-01",),
        ) as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row[0] == 45
    assert row[1] == 90


@pytest.mark.asyncio
async def test_heartbeat_does_not_consume_double_rate_limit_slot(app_client, db_path):
    await seed_node(db_path, "cnp-ratelimit-01")
    env_template = {
        "protocol_version": "CNPv1",
        "message_type": "heartbeat",
        "node_id": "cnp-ratelimit-01",
        "ts_utc": "2026-03-18T00:00:00Z",
        "qos": 1,
        "payload": {
            "seq": 1,
            "uptime_sec": 60,
            "free_heap_bytes": 100000,
            "wifi_rssi": -60,
            "queue_depth": 0,
            "status": "online",
        },
    }

    import uuid

    successes = 0
    for _ in range(55):
        env = {**env_template, "message_id": str(uuid.uuid4())}
        resp = await app_client.post("/api/node/heartbeat", headers=auth_headers(), json=env)
        if resp.status_code == 200:
            successes += 1

    assert successes == 55, f"Only {successes}/55 heartbeats succeeded — possible rate limit double-dip"

