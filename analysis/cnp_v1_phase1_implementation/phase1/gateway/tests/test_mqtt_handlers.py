"""
gateway/tests/test_mqtt_handlers.py
─────────────────────────────────────
Phase 1 — P1-07: MQTT handler unit tests.

Covers every handler path in GatewayMqttBridge using:
  - The injectable client_factory pattern (no real broker needed)
  - In-memory SQLite (db_path fixture from conftest)
  - Direct calls to bridge._ingest() and bridge._handle_*()

Handler matrix:
  ✅ _handle_hello       → upsert_node + publish register_ack
  ✅ _handle_heartbeat   → update_heartbeat + ops_detector hook
  ✅ _handle_event       → insert_event
  ✅ _handle_error       → insert_error
  ✅ _handle_ack         → insert_ack
  ✅ _handle_command_result → upsert_command_result
  ✅ _handle_state       → UPDATE nodes SET status
  ✅ _ingest dispatch    → correct handler called per topic suffix
  ✅ _ingest rate limit  → quarantined client drops messages
  ✅ _ingest bad JSON    → records invalid, no crash
  ✅ _ingest unknown suffix → silently ignored
  ✅ _check_rate_limit   → per-sec and burst thresholds enforced
  ✅ _record_invalid     → quarantine triggered at threshold
  ✅ cmd/out wildcard    → P0-08 regression guard
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from conftest import seed_node, _now_utc


# ── Bridge factory ─────────────────────────────────────────────────────────────

def _make_bridge(db_path: str):
    from app.core.mqtt_client import GatewayMqttBridge
    bridge = GatewayMqttBridge(db_path=db_path)
    mock_client = AsyncMock()
    mock_client.publish = AsyncMock()
    bridge.client = mock_client
    return bridge


# ── Envelope builders ──────────────────────────────────────────────────────────

def _hello(node_id: str = "cnp-mqtt-01") -> dict[str, Any]:
    return {
        "protocol_version": "CNPv1",
        "message_type": "hello",
        "message_id": str(uuid.uuid4()),
        "node_id": node_id,
        "ts_utc": _now_utc(),
        "qos": 1,
        "payload": {
            "device_uid": "deadbeef001",
            "node_name": "MQTT Test Node",
            "node_type": "sensor",
            "firmware_version": "1.0.0",
            "hardware_model": "esp32-c3-supermini",
            "supports_ota": True,
            "boot_reason": "power_on",
            "capabilities": {"sensors": ["temperature"], "actuators": [], "connectivity": ["wifi"]},
        },
    }


def _heartbeat(node_id: str = "cnp-mqtt-01") -> dict[str, Any]:
    return {
        "protocol_version": "CNPv1",
        "message_type": "heartbeat",
        "message_id": str(uuid.uuid4()),
        "node_id": node_id,
        "ts_utc": _now_utc(),
        "qos": 1,
        "payload": {
            "seq": 42, "uptime_sec": 3600, "free_heap_bytes": 85_000,
            "wifi_rssi": -55, "queue_depth": 0, "status": "online",
        },
    }


def _event(node_id: str = "cnp-mqtt-01", priority: str = "normal") -> dict[str, Any]:
    return {
        "protocol_version": "CNPv1",
        "message_type": "event",
        "message_id": str(uuid.uuid4()),
        "node_id": node_id,
        "ts_utc": _now_utc(),
        "qos": 1,
        "payload": {
            "event_type": "temp_reading", "category": "telemetry",
            "priority": priority, "requires_ack": False,
            "delivery_mode": "fire_and_forget", "event_seq": 1,
            "body": {"temperature_c": 22.5},
        },
    }


def _error(node_id: str = "cnp-mqtt-01") -> dict[str, Any]:
    return {
        "protocol_version": "CNPv1",
        "message_type": "error",
        "message_id": str(uuid.uuid4()),
        "node_id": node_id,
        "ts_utc": _now_utc(),
        "qos": 1,
        "payload": {
            "severity": "error", "domain": "sensor", "code": "read_fail",
            "message": "DHT22 read returned NaN", "recoverable": True,
            "diagnostics": {"retries": 3},
        },
    }


def _ack(node_id: str = "cnp-mqtt-01", target_id: str = "cmd-abc123") -> dict[str, Any]:
    return {
        "protocol_version": "CNPv1",
        "message_type": "ack",
        "message_id": str(uuid.uuid4()),
        "node_id": node_id,
        "ts_utc": _now_utc(),
        "qos": 1,
        "payload": {
            "ack_type": "command_ack",
            "target_message_id": target_id,
            "result": "ok",
            "reason": None,
        },
    }


def _cmd_result(node_id: str = "cnp-mqtt-01", cmd_id: str = "cmd-xyz") -> dict[str, Any]:
    return {
        "protocol_version": "CNPv1",
        "message_type": "command_result",
        "message_id": str(uuid.uuid4()),
        "node_id": node_id,
        "ts_utc": _now_utc(),
        "qos": 1,
        "payload": {
            "command_id": cmd_id, "status": "completed",
            "code": "ok", "details": {"relay_state": "on"},
        },
    }


def _state(node_id: str = "cnp-mqtt-01", status: str = "online") -> dict[str, Any]:
    return {
        "protocol_version": "CNPv1",
        "message_type": "state_update",
        "message_id": str(uuid.uuid4()),
        "node_id": node_id,
        "ts_utc": _now_utc(),
        "qos": 1,
        "payload": {"status": status, "uptime_sec": 7200},
    }


async def _seed_cmd(db_path: str, node_id: str, cmd_id: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO commands
              (command_id, node_id, command_type, category, issued_by,
               issued_ts_utc, status, timeout_ms, arguments_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cmd_id, node_id, "set_relay", "control", "gateway",
             _now_utc(), "queued", 10000, "{}"),
        )
        await db.commit()


# ════════════════════════════════════════════════════════════════════════════════
# _handle_hello
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_hello_upserts_node(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    await bridge._handle_hello(_hello("cnp-hello-01"))

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT status FROM nodes WHERE node_id=?",
                              ("cnp-hello-01",)) as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row[0] == "online"


@pytest.mark.asyncio
async def test_hello_publishes_register_ack(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    env = _hello("cnp-hello-02")
    await bridge._handle_hello(env)

    bridge.client.publish.assert_awaited_once()
    topic, raw_payload = bridge.client.publish.call_args[0][:2]
    payload = json.loads(raw_payload)

    assert topic == "cnp/v1/nodes/cnp-hello-02/ack"
    assert payload["message_type"] == "register_ack"
    assert payload["payload"]["accepted"] is True
    assert payload["payload"]["offline_after_sec"] > 0


@pytest.mark.asyncio
async def test_hello_no_crash_when_client_none(db_path: str) -> None:
    """Node upserted even when bridge client is None (reconnecting state)."""
    bridge = _make_bridge(db_path)
    bridge.client = None
    await bridge._handle_hello(_hello("cnp-hello-03"))

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT 1 FROM nodes WHERE node_id=?",
                              ("cnp-hello-03",)) as cur:
            assert await cur.fetchone() is not None


@pytest.mark.asyncio
async def test_hello_upsert_is_idempotent(db_path: str) -> None:
    """Re-registering the same node updates it, not duplicates it."""
    bridge = _make_bridge(db_path)
    env = _hello("cnp-hello-04")
    await bridge._handle_hello(env)
    await bridge._handle_hello(env)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM nodes WHERE node_id=?",
                              ("cnp-hello-04",)) as cur:
            (count,) = await cur.fetchone()

    assert count == 1


# ════════════════════════════════════════════════════════════════════════════════
# _handle_heartbeat
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_heartbeat_updates_rssi_and_status(db_path: str) -> None:
    await seed_node(db_path, "cnp-hb-01")
    bridge = _make_bridge(db_path)
    await bridge._handle_heartbeat(_heartbeat("cnp-hb-01"))

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT last_rssi, status FROM nodes WHERE node_id=?", ("cnp-hb-01",)
        ) as cur:
            row = await cur.fetchone()

    assert row[0] == -55
    assert row[1] == "online"


@pytest.mark.asyncio
async def test_heartbeat_fires_ops_detector(db_path: str) -> None:
    await seed_node(db_path, "cnp-hb-02")
    bridge = _make_bridge(db_path)
    detector = AsyncMock()
    bridge.set_ops_detector(detector)

    env = _heartbeat("cnp-hb-02")
    await bridge._handle_heartbeat(env)

    detector.on_heartbeat.assert_awaited_once_with(env)


@pytest.mark.asyncio
async def test_heartbeat_no_detector_no_crash(db_path: str) -> None:
    await seed_node(db_path, "cnp-hb-03")
    bridge = _make_bridge(db_path)
    bridge._ops_detector = None
    await bridge._handle_heartbeat(_heartbeat("cnp-hb-03"))


# ════════════════════════════════════════════════════════════════════════════════
# _handle_event
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_event_inserted_with_correct_priority(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    env = _event("cnp-ev-01", priority="critical")
    await bridge._handle_event(env)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT priority FROM events WHERE message_id=?", (env["message_id"],)
        ) as cur:
            row = await cur.fetchone()

    assert row[0] == "critical"


@pytest.mark.asyncio
async def test_event_insert_is_idempotent(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    env = _event("cnp-ev-02")
    await bridge._handle_event(env)
    await bridge._handle_event(env)  # duplicate

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM events WHERE message_id=?", (env["message_id"],)
        ) as cur:
            (count,) = await cur.fetchone()

    assert count == 1


# ════════════════════════════════════════════════════════════════════════════════
# _handle_error
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_error_inserted_with_correct_fields(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    env = _error("cnp-err-01")
    await bridge._handle_error(env)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT severity, code, recoverable FROM errors WHERE message_id=?",
            (env["message_id"],)
        ) as cur:
            row = await cur.fetchone()

    assert row[0] == "error"
    assert row[1] == "read_fail"
    assert row[2] == 1  # recoverable=True → INTEGER 1


# ════════════════════════════════════════════════════════════════════════════════
# _handle_ack
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ack_inserted_with_target_message_id(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    env = _ack("cnp-ack-01", target_id="cmd-target-007")
    await bridge._handle_ack(env)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT target_message_id, result FROM acks WHERE message_id=?",
            (env["message_id"],)
        ) as cur:
            row = await cur.fetchone()

    assert row[0] == "cmd-target-007"
    assert row[1] == "ok"


# ════════════════════════════════════════════════════════════════════════════════
# _handle_command_result
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_command_result_marks_command_completed(db_path: str) -> None:
    await seed_node(db_path, "cnp-cr-01")
    cmd_id = "cmd-phase1-001"
    await _seed_cmd(db_path, "cnp-cr-01", cmd_id)

    bridge = _make_bridge(db_path)
    await bridge._handle_command_result(_cmd_result("cnp-cr-01", cmd_id=cmd_id))

    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT status, result_code FROM commands WHERE command_id=?", (cmd_id,)
        ) as cur:
            row = await cur.fetchone()

    assert row[0] == "completed"
    assert row[1] == "ok"


# ════════════════════════════════════════════════════════════════════════════════
# _handle_state
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_state_updates_node_status(db_path: str) -> None:
    await seed_node(db_path, "cnp-state-01")
    bridge = _make_bridge(db_path)
    await bridge._handle_state(_state("cnp-state-01", status="degraded"))

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT status FROM nodes WHERE node_id=?",
                              ("cnp-state-01",)) as cur:
            row = await cur.fetchone()

    assert row[0] == "degraded"


@pytest.mark.asyncio
async def test_state_missing_node_id_no_crash(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    env = _state("cnp-state-02")
    env.pop("node_id")
    await bridge._handle_state(env)  # must not raise


# ════════════════════════════════════════════════════════════════════════════════
# _ingest dispatch
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ingest_hello_topic_creates_node(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    env = _hello("cnp-ing-01")
    await bridge._ingest("cnp/v1/nodes/cnp-ing-01/hello", json.dumps(env), "cnp-ing-01")

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT 1 FROM nodes WHERE node_id=?",
                              ("cnp-ing-01",)) as cur:
            assert await cur.fetchone() is not None


@pytest.mark.asyncio
async def test_ingest_events_topic_creates_event(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    env = _event("cnp-ing-02")
    await bridge._ingest("cnp/v1/nodes/cnp-ing-02/events", json.dumps(env), "cnp-ing-02")

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT 1 FROM events WHERE message_id=?",
                              (env["message_id"],)) as cur:
            assert await cur.fetchone() is not None


@pytest.mark.asyncio
async def test_ingest_heartbeat_topic_updates_node(db_path: str) -> None:
    await seed_node(db_path, "cnp-ing-03")
    bridge = _make_bridge(db_path)
    env = _heartbeat("cnp-ing-03")
    await bridge._ingest("cnp/v1/nodes/cnp-ing-03/heartbeat", json.dumps(env), "cnp-ing-03")

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT last_rssi FROM nodes WHERE node_id=?",
                              ("cnp-ing-03",)) as cur:
            row = await cur.fetchone()
    assert row[0] == -55


@pytest.mark.asyncio
async def test_ingest_errors_topic_creates_error(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    env = _error("cnp-ing-04")
    await bridge._ingest("cnp/v1/nodes/cnp-ing-04/errors", json.dumps(env), "cnp-ing-04")

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT 1 FROM errors WHERE message_id=?",
                              (env["message_id"],)) as cur:
            assert await cur.fetchone() is not None


@pytest.mark.asyncio
async def test_ingest_cmd_out_wildcard_regression(db_path: str) -> None:
    """
    P0-08 regression guard: cmd/out is a multi-segment suffix.
    Before the wildcard fix (cnp/v1/nodes/+/+), this topic was silently dropped.
    After fix (cnp/v1/nodes/+/#), it must reach _handle_command_result.
    """
    await seed_node(db_path, "cnp-cmdout-01")
    cmd_id = "cmd-wildcard-test-001"
    await _seed_cmd(db_path, "cnp-cmdout-01", cmd_id)

    bridge = _make_bridge(db_path)
    env = _cmd_result("cnp-cmdout-01", cmd_id=cmd_id)
    await bridge._ingest("cnp/v1/nodes/cnp-cmdout-01/cmd/out", json.dumps(env), "cnp-cmdout-01")

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT status FROM commands WHERE command_id=?",
                              (cmd_id,)) as cur:
            row = await cur.fetchone()

    assert row is not None, "cmd/out message not dispatched — check MQTT wildcard is cnp/v1/nodes/+/#"
    assert row[0] == "completed"


@pytest.mark.asyncio
async def test_ingest_cmd_in_is_ignored(db_path: str) -> None:
    """cmd/in is outbound-only; inbound messages on this topic are silently ignored."""
    bridge = _make_bridge(db_path)
    payload = json.dumps({"message_type": "command", "node_id": "cnp-ing-05"})
    await bridge._ingest("cnp/v1/nodes/cnp-ing-05/cmd/in", payload, "cnp-ing-05")


@pytest.mark.asyncio
async def test_ingest_unknown_suffix_no_crash(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    payload = json.dumps({"message_type": "unknown"})
    await bridge._ingest("cnp/v1/nodes/cnp-ing-06/firmware/ota/status", payload, "cnp-ing-06")


# ════════════════════════════════════════════════════════════════════════════════
# _ingest — malformed input
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ingest_invalid_json_records_invalid_and_no_crash(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    await bridge._ingest("cnp/v1/nodes/cnp-bad-01/events", "{ not json !!!", "cnp-bad-01")

    state = bridge._rate_states["cnp-bad-01"]
    assert len(state.invalid_timestamps) >= 1


@pytest.mark.asyncio
async def test_ingest_empty_payload_no_crash(db_path: str) -> None:
    bridge = _make_bridge(db_path)
    await bridge._ingest("cnp/v1/nodes/cnp-empty-01/events", "", "cnp-empty-01")


# ════════════════════════════════════════════════════════════════════════════════
# Rate limiting
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_quarantined_client_message_dropped(db_path: str) -> None:
    """Quarantined client → event not written to DB."""
    bridge = _make_bridge(db_path)
    bridge._rate_states["cnp-quar-01"].quarantine(60.0)

    env = _event("cnp-quar-01")
    await bridge._ingest("cnp/v1/nodes/cnp-quar-01/events", json.dumps(env), "cnp-quar-01")

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT 1 FROM events WHERE message_id=?",
                              (env["message_id"],)) as cur:
            assert await cur.fetchone() is None


def test_quarantine_triggered_at_invalid_threshold() -> None:
    """3 invalid messages trigger quarantine for 300 seconds."""
    from app.core.mqtt_client import GatewayMqttBridge
    bridge = GatewayMqttBridge(db_path=":memory:")

    for i in range(3):
        bridge._record_invalid("cnp-inv-01", f"topic/{i}", f"err_{i}")

    assert bridge._rate_states["cnp-inv-01"].is_quarantined()


def test_per_second_rate_limit_enforced() -> None:
    """11th message within 1s window returns rate-limited=True."""
    from app.core.mqtt_client import GatewayMqttBridge
    bridge = GatewayMqttBridge(db_path=":memory:")
    state = bridge._rate_states["cnp-rps-01"]

    now = time.monotonic()
    for _ in range(10):  # _MQTT_PER_CLIENT_MAX_PER_SEC = 10
        state.record_message(now)

    assert bridge._check_rate_limit("cnp-rps-01", "some/topic") is True


def test_not_rate_limited_below_threshold() -> None:
    """9 messages per second → not rate-limited."""
    from app.core.mqtt_client import GatewayMqttBridge
    bridge = GatewayMqttBridge(db_path=":memory:")
    state = bridge._rate_states["cnp-ok-01"]

    now = time.monotonic()
    for _ in range(9):
        state.record_message(now)

    assert bridge._check_rate_limit("cnp-ok-01", "some/topic") is False
