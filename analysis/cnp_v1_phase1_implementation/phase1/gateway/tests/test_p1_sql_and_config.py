"""
gateway/tests/test_p1_sql_and_config.py
─────────────────────────────────────────
Phase 1 tests for:
  P1-01 — SQL injection remediation (list_nodes, list_events allowlists)
  P1-02 — NodeConfigUpdate Pydantic validation on PATCH /nodes/{id}/config

These tests prove the fix holds and will catch any regression that re-introduces
f-string SQL or removes input validation from the config endpoint.
"""
from __future__ import annotations

import pytest

from conftest import auth_headers, seed_node, _now_utc, make_hello_envelope


# ── list_nodes — allowlist filter (P1-01) ─────────────────────────────────────

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
@pytest.mark.parametrize("bad_status", [
    "'; DROP TABLE nodes; --",
    "online OR 1=1",
    "UNION SELECT * FROM nodes--",
    "1; SELECT * FROM node_config",
    "<script>alert(1)</script>",
    "",
    "superadmin",
    "ONLINE",          # case mismatch — not in allowlist
    "unknown_status",
])
async def test_list_nodes_invalid_status_returns_400(app_client, bad_status):
    """P1-01: any status value not in allowlist must return 400, never execute."""
    response = await app_client.get(f"/api/nodes?status={bad_status}")
    assert response.status_code in (400, 422), (
        f"Expected 400/422 for status={bad_status!r}, got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_list_nodes_valid_statuses_all_accepted(app_client, db_path):
    """All four valid status values must be accepted without error."""
    for status in ("online", "offline", "unknown", "retired"):
        response = await app_client.get(f"/api/nodes?status={status}")
        assert response.status_code == 200, f"Expected 200 for valid status={status}"


@pytest.mark.asyncio
async def test_list_nodes_secret_hash_not_in_response(app_client, db_path):
    """P1-06: node_secret_hash must never appear in API response."""
    await seed_node(db_path, "cnp-secret-check")
    response = await app_client.get("/api/nodes")
    assert response.status_code == 200
    raw_text = response.text
    assert "node_secret_hash" not in raw_text
    assert "secret_hash" not in raw_text


# ── list_events — allowlist filter (P1-01) ────────────────────────────────────

@pytest.mark.asyncio
async def test_list_events_no_filter_returns_200(app_client):
    response = await app_client.get("/api/events")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_list_events_valid_priority_filter(app_client, db_path):
    """Insert a high-priority event and verify filter returns only matching rows."""
    import aiosqlite, json, uuid
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
@pytest.mark.parametrize("bad_priority", [
    "'; DROP TABLE events; --",
    "high OR 1=1",
    "UNION SELECT * FROM nodes--",
    "HIGH",              # case mismatch
    "medium",            # not in allowlist
    "urgent",
    "1=1",
])
async def test_list_events_invalid_priority_returns_400(app_client, bad_priority):
    """P1-01: invalid priority values must return 400."""
    response = await app_client.get(f"/api/events?priority={bad_priority}")
    assert response.status_code in (400, 422), (
        f"Expected 400/422 for priority={bad_priority!r}, got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_list_events_valid_priorities_all_accepted(app_client):
    """All four valid priority values must return 200."""
    for priority in ("low", "normal", "high", "critical"):
        response = await app_client.get(f"/api/events?priority={priority}")
        assert response.status_code == 200, f"Expected 200 for priority={priority}"


# ── PATCH /nodes/{id}/config — Pydantic validation (P1-02) ───────────────────

@pytest.mark.asyncio
async def test_config_update_valid_values(app_client, db_path):
    """Valid heartbeat and report intervals must be accepted and persisted."""
    await seed_node(db_path, "cnp-cfg-01")
    response = await app_client.patch(
        "/api/nodes/cnp-cfg-01/config",
        json={"heartbeat_interval_sec": 30, "report_interval_sec": 120},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_config_update_persists_to_db(app_client, db_path):
    """Config values must actually be written to node_config table."""
    import aiosqlite
    await seed_node(db_path, "cnp-cfg-persist")
    await app_client.patch(
        "/api/nodes/cnp-cfg-persist/config",
        json={"heartbeat_interval_sec": 45, "report_interval_sec": 90},
    )

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM node_config WHERE node_id=?", ("cnp-cfg-persist",)
        ) as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row["heartbeat_interval_sec"] == 45
    assert row["report_interval_sec"] == 90


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,expected_code", [
    # Below minimum (10)
    ({"heartbeat_interval_sec": 9, "report_interval_sec": 60}, 422),
    ({"heartbeat_interval_sec": 0, "report_interval_sec": 60}, 422),
    ({"heartbeat_interval_sec": -1, "report_interval_sec": 60}, 422),
    ({"heartbeat_interval_sec": 60, "report_interval_sec": 9}, 422),
    # Above maximum (3600)
    ({"heartbeat_interval_sec": 3601, "report_interval_sec": 60}, 422),
    ({"heartbeat_interval_sec": 60, "report_interval_sec": 99999}, 422),
    # Type errors
    ({"heartbeat_interval_sec": "fast", "report_interval_sec": 60}, 422),
    ({"heartbeat_interval_sec": None, "report_interval_sec": 60}, 422),
    ({"heartbeat_interval_sec": 3.5, "report_interval_sec": 60}, 422),  # float → rejected
])
async def test_config_update_rejects_invalid_values(app_client, db_path, payload, expected_code):
    """P1-02: out-of-range or wrong-type values must be rejected before reaching DB."""
    await seed_node(db_path, "cnp-cfg-invalid")
    response = await app_client.patch("/api/nodes/cnp-cfg-invalid/config", json=payload)
    assert response.status_code == expected_code, (
        f"Expected {expected_code} for payload={payload}, got {response.status_code}: {response.text}"
    )


@pytest.mark.asyncio
async def test_config_update_boundary_values_accepted(app_client, db_path):
    """Boundary values (10 and 3600) must be accepted — they are valid."""
    await seed_node(db_path, "cnp-cfg-boundary")
    # Min boundary
    r = await app_client.patch(
        "/api/nodes/cnp-cfg-boundary/config",
        json={"heartbeat_interval_sec": 10, "report_interval_sec": 10},
    )
    assert r.status_code == 200
    # Max boundary
    r = await app_client.patch(
        "/api/nodes/cnp-cfg-boundary/config",
        json={"heartbeat_interval_sec": 3600, "report_interval_sec": 3600},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_config_update_node_not_found(app_client):
    """PATCH config on non-existent node must return 404."""
    response = await app_client.patch(
        "/api/nodes/does-not-exist/config",
        json={"heartbeat_interval_sec": 60, "report_interval_sec": 60},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "node_not_found"


@pytest.mark.asyncio
async def test_config_update_defaults_applied_when_fields_omitted(app_client, db_path):
    """Omitting fields should apply model defaults (60/60), not crash."""
    await seed_node(db_path, "cnp-cfg-defaults")
    response = await app_client.patch(
        "/api/nodes/cnp-cfg-defaults/config",
        json={},  # empty body — Pydantic applies defaults
    )
    assert response.status_code == 200


# ── Integration: node lifecycle with fixed routes ─────────────────────────────

@pytest.mark.asyncio
async def test_full_lifecycle_hello_to_config(app_client, db_path):
    """
    Integration: hello → verify node exists → update config → verify config.
    Exercises the fixed routes.py end-to-end with all Phase 1 fixes applied.
    """
    import aiosqlite
    node_id = "cnp-lifecycle-p1"

    # 1. Hello
    r = await app_client.post(
        "/api/node/hello",
        headers=auth_headers(),
        json=make_hello_envelope(node_id=node_id),
    )
    assert r.status_code == 200
    assert r.json()["registered"] is True

    # 2. Node should be queryable — and NOT contain secret hash
    r = await app_client.get(f"/api/nodes/{node_id}")
    assert r.status_code == 200
    assert r.json()["node_id"] == node_id
    assert "node_secret_hash" not in r.text

    # 3. Update config with validated values
    r = await app_client.patch(
        f"/api/nodes/{node_id}/config",
        json={"heartbeat_interval_sec": 30, "report_interval_sec": 60},
    )
    assert r.status_code == 200

    # 4. Verify persisted
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT heartbeat_interval_sec FROM node_config WHERE node_id=?", (node_id,)
        ) as cur:
            row = await cur.fetchone()
    assert row["heartbeat_interval_sec"] == 30
