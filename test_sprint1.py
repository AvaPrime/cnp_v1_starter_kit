"""
CNP EPIC-01 — P1-10
Test suite covering:
  test_nodes.py       — list, get, 404, field exclusion (P1-02)
  test_validation.py  — 12 invalid envelope fixtures (P1-06)
  test_rate_limiting.py — HTTP throttle, isolation (P1-04)
  test_integration.py — 11-step lifecycle (P1-10 / port of test_flow.sh)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from .conftest import (
    auth_headers,
    make_event_envelope,
    make_heartbeat_envelope,
    make_hello_envelope,
    seed_node,
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ================================================================
#  test_nodes — P1-02 field exclusion + CRUD
# ================================================================

class TestNodes:

    @pytest.mark.asyncio
    async def test_list_nodes_empty(self, app_client):
        r = await app_client.get("/api/nodes")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_list_nodes_after_registration(self, app_client, db_path):
        await seed_node(db_path, "cnp-list-01")
        r = await app_client.get("/api/nodes")
        assert r.status_code == 200
        rows = r.json()
        assert any(n["node_id"] == "cnp-list-01" for n in rows)

    @pytest.mark.asyncio
    async def test_get_node_detail(self, app_client, db_path):
        await seed_node(db_path, "cnp-detail-01")
        r = await app_client.get("/api/nodes/cnp-detail-01")
        assert r.status_code == 200
        data = r.json()
        assert data["node_id"] == "cnp-detail-01"

    @pytest.mark.asyncio
    async def test_get_node_404(self, app_client):
        r = await app_client.get("/api/nodes/cnp-does-not-exist")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_node_response_excludes_secret_fields(self, app_client, db_path):
        """P1-02: node_secret_hash must never appear in API response."""
        await seed_node(db_path, "cnp-secret-test")
        r = await app_client.get("/api/nodes/cnp-secret-test")
        assert r.status_code == 200
        body = r.json()
        excluded = ["node_secret_hash", "metadata_json"]
        for field in excluded:
            assert field not in body, f"Field {field!r} found in response — must be excluded"

    @pytest.mark.asyncio
    async def test_list_nodes_response_excludes_secret_fields(self, app_client, db_path):
        await seed_node(db_path, "cnp-list-secret")
        r = await app_client.get("/api/nodes")
        assert r.status_code == 200
        for node in r.json():
            assert "node_secret_hash" not in node
            assert "metadata_json" not in node


# ================================================================
#  test_validation — P1-06 Pydantic envelope rejection
# ================================================================

class TestValidation:
    """
    12 invalid envelope fixtures — all must return 422,
    none must reach the DB.
    """

    INVALID_FIXTURES = [
        # 1. Missing message_id
        {
            "protocol_version": "CNPv1", "message_type": "heartbeat",
            "node_id": "cnp-val-01", "ts_utc": "2026-03-18T10:00:00Z",
            "qos": 1, "payload": {"status": "online", "uptime_sec": 10},
        },
        # 2. Wrong protocol_version
        {
            "protocol_version": "CNPv99", "message_type": "heartbeat",
            "message_id": "x" * 10,
            "node_id": "cnp-val-01", "ts_utc": "2026-03-18T10:00:00Z",
            "qos": 1, "payload": {},
        },
        # 3. Invalid node_id pattern (uppercase)
        {
            "protocol_version": "CNPv1", "message_type": "heartbeat",
            "message_id": "a" * 10,
            "node_id": "CNP-VAL-01", "ts_utc": "2026-03-18T10:00:00Z",
            "qos": 1, "payload": {},
        },
        # 4. Invalid node_id (too short)
        {
            "protocol_version": "CNPv1", "message_type": "heartbeat",
            "message_id": "b" * 10,
            "node_id": "ab", "ts_utc": "2026-03-18T10:00:00Z",
            "qos": 1, "payload": {},
        },
        # 5. Invalid node_id (special chars)
        {
            "protocol_version": "CNPv1", "message_type": "heartbeat",
            "message_id": "c" * 10,
            "node_id": "cnp_val_01", "ts_utc": "2026-03-18T10:00:00Z",
            "qos": 1, "payload": {},
        },
        # 6. ts_utc missing Z suffix
        {
            "protocol_version": "CNPv1", "message_type": "heartbeat",
            "message_id": "d" * 10,
            "node_id": "cnp-val-01", "ts_utc": "2026-03-18T10:00:00+00:00",
            "qos": 1, "payload": {},
        },
        # 7. qos invalid value
        {
            "protocol_version": "CNPv1", "message_type": "heartbeat",
            "message_id": "e" * 10,
            "node_id": "cnp-val-01", "ts_utc": "2026-03-18T10:00:00Z",
            "qos": 2, "payload": {},
        },
        # 8. Invalid message_type
        {
            "protocol_version": "CNPv1", "message_type": "invalid_type",
            "message_id": "f" * 10,
            "node_id": "cnp-val-01", "ts_utc": "2026-03-18T10:00:00Z",
            "qos": 1, "payload": {},
        },
        # 9. Missing payload
        {
            "protocol_version": "CNPv1", "message_type": "heartbeat",
            "message_id": "g" * 10,
            "node_id": "cnp-val-01", "ts_utc": "2026-03-18T10:00:00Z",
            "qos": 1,
        },
        # 10. message_id too short (< 4 chars)
        {
            "protocol_version": "CNPv1", "message_type": "heartbeat",
            "message_id": "ab",
            "node_id": "cnp-val-01", "ts_utc": "2026-03-18T10:00:00Z",
            "qos": 0, "payload": {},
        },
        # 11. node_id too long (> 64 chars)
        {
            "protocol_version": "CNPv1", "message_type": "heartbeat",
            "message_id": "h" * 10,
            "node_id": "cnp-" + "a" * 61, "ts_utc": "2026-03-18T10:00:00Z",
            "qos": 0, "payload": {},
        },
        # 12. Completely empty body
        {},
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fixture_idx", list(range(len(INVALID_FIXTURES))))
    async def test_invalid_envelope_returns_422(self, app_client, fixture_idx):
        body = self.INVALID_FIXTURES[fixture_idx]
        r = await app_client.post(
            "/api/node/heartbeat",
            json=body,
            headers=auth_headers(),
        )
        assert r.status_code == 422, (
            f"Fixture {fixture_idx} expected 422 but got {r.status_code}: {r.text}"
        )

    @pytest.mark.asyncio
    async def test_valid_envelope_passes(self, app_client, db_path):
        """A valid envelope must not be rejected."""
        await seed_node(db_path, "cnp-valid-01")
        hb = make_heartbeat_envelope("cnp-valid-01")
        r = await app_client.post("/api/node/heartbeat", json=hb, headers=auth_headers())
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_v1_envelope_normalised(self, app_client, db_path):
        """V1 key names (protocol, timestamp) must be accepted and normalised."""
        await seed_node(db_path, "cnp-v1-01")
        v1_envelope = {
            "protocol": "CNPv1",           # V1 key
            "message_type": "heartbeat",
            "message_id": "v1-msg-001",
            "node_id": "cnp-v1-01",
            "timestamp": "2026-03-18T10:00:00Z",   # V1 key
            "qos": 1,
            "payload": {"status": "online", "uptime_sec": 30},
        }
        r = await app_client.post("/api/node/heartbeat", json=v1_envelope, headers=auth_headers())
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self, app_client, db_path):
        hb = make_heartbeat_envelope("cnp-auth-01")
        r = await app_client.post("/api/node/heartbeat", json=hb)  # no auth header
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self, app_client, db_path):
        hb = make_heartbeat_envelope("cnp-auth-02")
        r = await app_client.post(
            "/api/node/heartbeat",
            json=hb,
            headers={"X-CNP-Node-Token": "wrong-token"},
        )
        assert r.status_code == 401


# ================================================================
#  test_rate_limiting — P1-04
# ================================================================

class TestRateLimiting:

    @pytest.mark.asyncio
    async def test_second_client_unaffected_when_first_throttled(
        self, app_client, db_path
    ):
        """
        Client A exhausts its per-node budget.
        Client B (different node_id) must still succeed.
        """
        await seed_node(db_path, "cnp-rate-a")
        await seed_node(db_path, "cnp-rate-b")

        from app.core.rate_limit import _node_limiter, _SlidingWindow
        # Pre-fill node-a's window to simulate exhaustion
        import time
        bucket = _node_limiter._buckets["cnp-rate-a"]
        now = time.monotonic()
        for _ in range(_node_limiter.max_count):
            bucket.append(now)

        # Node-a should now be throttled
        hb_a = make_heartbeat_envelope("cnp-rate-a")
        r_a = await app_client.post("/api/node/heartbeat", json=hb_a, headers=auth_headers())
        assert r_a.status_code == 429
        assert "Retry-After" in r_a.headers

        # Node-b should be unaffected
        hb_b = make_heartbeat_envelope("cnp-rate-b")
        r_b = await app_client.post("/api/node/heartbeat", json=hb_b, headers=auth_headers())
        assert r_b.status_code == 200

    @pytest.mark.asyncio
    async def test_429_includes_retry_after(self, app_client, db_path):
        await seed_node(db_path, "cnp-retry-01")
        from app.core.rate_limit import _node_limiter
        import time
        bucket = _node_limiter._buckets["cnp-retry-01"]
        now = time.monotonic()
        for _ in range(_node_limiter.max_count):
            bucket.append(now)

        hb = make_heartbeat_envelope("cnp-retry-01")
        r = await app_client.post("/api/node/heartbeat", json=hb, headers=auth_headers())
        assert r.status_code == 429
        retry = int(r.headers.get("Retry-After", 0))
        assert 1 <= retry <= 61


# ================================================================
#  test_integration — 11-step lifecycle (port of test_flow.sh)
# ================================================================

class TestIntegration:
    """
    Complete node lifecycle in a single test class.
    Each method builds on state from the previous one.
    State is shared via class attributes.
    """
    _node_id = "cnp-office-temp-01"
    _cmd_id: str = ""

    @pytest.mark.asyncio
    async def test_01_health(self, app_client):
        r = await app_client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["db_ok"] is True

    @pytest.mark.asyncio
    async def test_02_hello_registration(self, app_client):
        hello = make_hello_envelope(self._node_id, "Office Climate Node", "office")
        r = await app_client.post("/api/node/hello", json=hello, headers=auth_headers())
        assert r.status_code == 200
        body = r.json()
        assert body["registered"] is True
        assert "config" in body

    @pytest.mark.asyncio
    async def test_03_node_appears_in_registry(self, app_client):
        r = await app_client.get("/api/nodes")
        assert r.status_code == 200
        node_ids = [n["node_id"] for n in r.json()]
        assert self._node_id in node_ids

    @pytest.mark.asyncio
    async def test_04_heartbeat(self, app_client):
        hb = make_heartbeat_envelope(self._node_id)
        r = await app_client.post("/api/node/heartbeat", json=hb, headers=auth_headers())
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_05_node_is_online(self, app_client):
        r = await app_client.get(f"/api/nodes/{self._node_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "online"

    @pytest.mark.asyncio
    async def test_06_telemetry_event(self, app_client):
        event = make_event_envelope(self._node_id, priority="normal", category="telemetry")
        r = await app_client.post("/api/node/event", json=event, headers=auth_headers())
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_07_alert_event_appears_in_alerts(self, app_client):
        event = make_event_envelope(self._node_id, priority="high", category="alert")
        r = await app_client.post("/api/node/event", json=event, headers=auth_headers())
        assert r.status_code == 200

        alerts = await app_client.get("/api/alerts")
        assert alerts.status_code == 200
        assert len(alerts.json()) >= 1

    @pytest.mark.asyncio
    async def test_08_error_report(self, app_client):
        error_env = {
            "protocol_version": "CNPv1",
            "message_type": "error",
            "message_id": str(uuid.uuid4()),
            "node_id": self._node_id,
            "ts_utc": _now(),
            "qos": 1,
            "payload": {
                "severity": "error",
                "domain": "SENSOR",
                "code": "SENSOR_READ_FAIL",
                "message": "DHT22 returned NaN",
                "recoverable": True,
            },
        }
        r = await app_client.post("/api/node/error", json=error_env, headers=auth_headers())
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_09_issue_command(self, app_client):
        r = await app_client.post(
            f"/api/nodes/{self._node_id}/commands",
            json={
                "command_type": "set_relay",
                "category": "control",
                "timeout_ms": 5000,
                "arguments": {"state": "on"},
            },
        )
        assert r.status_code == 200
        TestIntegration._cmd_id = r.json()["command_id"]
        assert TestIntegration._cmd_id

    @pytest.mark.asyncio
    async def test_10_poll_command(self, app_client):
        r = await app_client.get(
            f"/api/node/commands/{self._node_id}",
            headers=auth_headers(),
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("command") is True

    @pytest.mark.asyncio
    async def test_11_command_ack(self, app_client):
        ack = {
            "protocol_version": "CNPv1",
            "message_type": "command_result",
            "message_id": str(uuid.uuid4()),
            "node_id": self._node_id,
            "ts_utc": _now(),
            "qos": 1,
            "payload": {
                "command_id":  TestIntegration._cmd_id,
                "status":      "executed",
                "duration_ms": 42,
                "code":        "CMD_OK",
                "details":     {},
            },
        }
        r = await app_client.post("/api/node/command_result", json=ack, headers=auth_headers())
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_12_summary_endpoint(self, app_client):
        r = await app_client.get("/api/summary")
        assert r.status_code == 200
        data = r.json()
        assert data.get("total_nodes", 0) >= 1
        assert "online_count" in data
        assert "alerts_24h" in data

    @pytest.mark.asyncio
    async def test_13_offline_detection(self, app_client, db_path):
        """
        Simulate stale node by backdating last_seen_utc.
        Trigger mark_offline_nodes() and verify status transitions.
        """
        import aiosqlite
        from app.core.registry import mark_offline_nodes

        # Backdate last_seen to 200s ago (> offline_after_sec=180)
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """UPDATE nodes SET last_seen_utc = datetime('now', '-200 seconds')
                   WHERE node_id = ?""",
                (self._node_id,),
            )
            await db.commit()

        # Trigger watcher
        from app.core.config import settings
        count = await mark_offline_nodes(db_path, 180)
        assert count >= 1

        r = await app_client.get(f"/api/nodes/{self._node_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "offline"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
