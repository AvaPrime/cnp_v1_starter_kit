from __future__ import annotations

import pytest

from conftest import _now_utc, auth_headers, make_hello_envelope, seed_node


@pytest.mark.asyncio
async def test_list_nodes_no_filter_returns_all(app_client, db_path):
    await seed_node(db_path, "cnp-list-01")
    await seed_node(db_path, "cnp-list-02")

    response = await app_client.get("/api/nodes")
    assert response.status_code == 200
    ids = [n["node_id"] for n in response.json()]
    assert "cnp-list-01" in ids
    assert "cnp-list-02" in ids


@pytest.mark.asyncio
async def test_list_nodes_valid_status_filter(app_client, db_path):
    await seed_node(db_path, "cnp-online-01")

    response = await app_client.get("/api/nodes?status=online")
    assert response.status_code == 200
    nodes = response.json()
    assert all(n["status"] == "online" for n in nodes)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_status",
    [
        "'; DROP TABLE nodes; --",
        "online OR 1=1",
        "UNION SELECT * FROM nodes--",
        "1; SELECT * FROM node_config",
        "<script>alert(1)</script>",
        "superadmin",
        "ONLINE",
        "unknown_status",
    ],
)
async def test_list_nodes_invalid_status_returns_400(app_client, bad_status):
    response = await app_client.get(f"/api/nodes?status={bad_status}")
    assert response.status_code in (400, 422), (
        f"Expected 400/422 for status={bad_status!r}, got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_list_nodes_valid_statuses_all_accepted(app_client, db_path):
    for status in ("online", "offline", "unknown", "retired"):
        response = await app_client.get(f"/api/nodes?status={status}")
        assert response.status_code == 200, f"Expected 200 for valid status={status}"


@pytest.mark.asyncio
async def test_list_nodes_secret_hash_not_in_response(app_client, db_path):
    await seed_node(db_path, "cnp-secret-check")
    response = await app_client.get("/api/nodes")
    assert response.status_code == 200
    raw_text = response.text
    assert "node_secret_hash" not in raw_text
    assert "secret_hash" not in raw_text


@pytest.mark.asyncio
async def test_list_events_no_filter_returns_200(app_client):
    response = await app_client.get("/api/events")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_list_events_valid_priority_filter(app_client, db_path):
    import aiosqlite
    import uuid

    node_id = "cnp-evt-prio-01"
    await seed_node(db_path, node_id)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT INTO events
               (message_id, node_id, ts_utc, category, event_type, priority, requires_ack, body_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), node_id, _now_utc(), "telemetry", "temp_spike", "high", 0, "{}"),
        )
        await db.execute(
            """INSERT INTO events
               (message_id, node_id, ts_utc, category, event_type, priority, requires_ack, body_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), node_id, _now_utc(), "telemetry", "temp_ok", "normal", 0, "{}"),
        )
        await db.commit()

    response = await app_client.get("/api/events?priority=high")
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1
    assert events[0]["priority"] == "high"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_priority",
    [
        "'; DROP TABLE events; --",
        "high OR 1=1",
        "UNION SELECT * FROM nodes--",
        "HIGH",
        "medium",
        "urgent",
        "1=1",
    ],
)
async def test_list_events_invalid_priority_returns_400(app_client, bad_priority):
    response = await app_client.get(f"/api/events?priority={bad_priority}")
    assert response.status_code in (400, 422), (
        f"Expected 400/422 for priority={bad_priority!r}, got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_list_events_valid_priorities_all_accepted(app_client):
    for priority in ("low", "normal", "high", "critical"):
        response = await app_client.get(f"/api/events?priority={priority}")
        assert response.status_code == 200, f"Expected 200 for priority={priority}"


@pytest.mark.asyncio
async def test_config_update_valid_values(app_client, db_path):
    await seed_node(db_path, "cnp-cfg-01")
    response = await app_client.patch(
        "/api/nodes/cnp-cfg-01/config",
        json={"heartbeat_interval_sec": 30, "report_interval_sec": 120},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_config_update_persists_to_db(app_client, db_path):
    import aiosqlite

    await seed_node(db_path, "cnp-cfg-persist")
    await app_client.patch(
        "/api/nodes/cnp-cfg-persist/config",
        json={"heartbeat_interval_sec": 45, "report_interval_sec": 90},
    )

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM node_config WHERE node_id=?", ("cnp-cfg-persist",)) as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row["heartbeat_interval_sec"] == 45
    assert row["report_interval_sec"] == 90


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected_code",
    [
        ({"heartbeat_interval_sec": 9, "report_interval_sec": 60}, 400),
        ({"heartbeat_interval_sec": 0, "report_interval_sec": 60}, 400),
        ({"heartbeat_interval_sec": -1, "report_interval_sec": 60}, 400),
        ({"heartbeat_interval_sec": 60, "report_interval_sec": 9}, 400),
        ({"heartbeat_interval_sec": 3601, "report_interval_sec": 60}, 400),
        ({"heartbeat_interval_sec": 60, "report_interval_sec": 99999}, 400),
        ({"heartbeat_interval_sec": "fast", "report_interval_sec": 60}, 400),
        ({"heartbeat_interval_sec": None, "report_interval_sec": 60}, 400),
        ({"heartbeat_interval_sec": 3.5, "report_interval_sec": 60}, 400),
    ],
)
async def test_config_update_rejects_invalid_values(app_client, db_path, payload, expected_code):
    await seed_node(db_path, "cnp-cfg-invalid")
    response = await app_client.patch("/api/nodes/cnp-cfg-invalid/config", json=payload)
    assert response.status_code == expected_code, (
        f"Expected {expected_code} for payload={payload}, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_config_update_boundary_values_accepted(app_client, db_path):
    await seed_node(db_path, "cnp-cfg-boundary")
    r = await app_client.patch(
        "/api/nodes/cnp-cfg-boundary/config",
        json={"heartbeat_interval_sec": 10, "report_interval_sec": 10},
    )
    assert r.status_code == 200
    r = await app_client.patch(
        "/api/nodes/cnp-cfg-boundary/config",
        json={"heartbeat_interval_sec": 3600, "report_interval_sec": 3600},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_config_update_node_not_found(app_client):
    response = await app_client.patch(
        "/api/nodes/does-not-exist/config",
        json={"heartbeat_interval_sec": 60, "report_interval_sec": 60},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "node_not_found"


@pytest.mark.asyncio
async def test_config_update_defaults_applied_when_fields_omitted(app_client, db_path):
    await seed_node(db_path, "cnp-cfg-defaults")
    response = await app_client.patch(
        "/api/nodes/cnp-cfg-defaults/config",
        json={},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_full_lifecycle_hello_to_config(app_client, db_path):
    import aiosqlite

    node_id = "cnp-lifecycle-p1"

    r = await app_client.post(
        "/api/node/hello",
        headers=auth_headers(),
        json=make_hello_envelope(node_id=node_id),
    )
    assert r.status_code == 200
    assert r.json()["registered"] is True

    r = await app_client.get(f"/api/nodes/{node_id}")
    assert r.status_code == 200
    assert r.json()["node_id"] == node_id
    assert "node_secret_hash" not in r.text

    r = await app_client.patch(
        f"/api/nodes/{node_id}/config",
        json={"heartbeat_interval_sec": 30, "report_interval_sec": 60},
    )
    assert r.status_code == 200

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT heartbeat_interval_sec FROM node_config WHERE node_id=?",
            (node_id,),
        ) as cur:
            row = await cur.fetchone()
    assert row["heartbeat_interval_sec"] == 30

