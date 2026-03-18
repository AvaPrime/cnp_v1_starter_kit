"""
gateway/tests/conftest.py
──────────────────────────
Shared test fixtures for CNP gateway test suite.

Changes from audit:
  - ADMIN_TOKEN added to os.environ.setdefault (P0-05)
  - MockMqttBridge pulled into conftest (was duplicated in mqtt_client.py)
  - seed_node helper made async-safe
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import aiosqlite
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Set tokens before importing app — order matters
os.environ.setdefault("BOOTSTRAP_TOKEN", "test-bootstrap-token-001")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token-001")
os.environ.setdefault("GATEWAY_DB_PATH", ":memory:")

import sys
from pathlib import Path
sys.path.insert(0, str((Path(__file__).parent.parent).resolve()))

from app.core.db import init_db


# ── In-memory DB fixture ──────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_path(tmp_path) -> str:
    path = str(tmp_path / "test_gateway.db")
    await init_db(path)
    return path


# ── Mock MQTT bridge ──────────────────────────────────────────────────────────

class MockMqttBridge:
    """In-memory MQTT bridge for test injection. No broker required."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self._ops_detector = None

    def set_ops_detector(self, detector) -> None:
        self._ops_detector = detector

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def publish_command(self, node_id: str, payload: dict) -> None:
        import json
        topic = f"cnp/v1/nodes/{node_id}/cmd/in"
        self.published.append((topic, json.dumps(payload)))

    def last_published_to(self, topic_suffix: str) -> str | None:
        for topic, payload in reversed(self.published):
            if topic.endswith(topic_suffix):
                return payload
        return None


@pytest.fixture
def mock_bridge() -> MockMqttBridge:
    return MockMqttBridge()


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def app_client(db_path: str, mock_bridge: MockMqttBridge) -> AsyncGenerator:
    import app.main as main_module
    from app.core import config as cfg_module
    from dataclasses import replace
    import app.api.routes as routes_module
    import app.api.compat as compat_module
    import app.api.admin as admin_module

    original_bridge = main_module.bridge
    original_settings = cfg_module.settings

    cfg_module.settings = replace(original_settings, gateway_db_path=db_path)
    main_module.bridge = mock_bridge
    main_module.settings = cfg_module.settings
    routes_module.settings = cfg_module.settings
    compat_module.settings = cfg_module.settings
    admin_module.settings = cfg_module.settings

    await init_db(db_path)

    from app.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    main_module.bridge = original_bridge
    cfg_module.settings = original_settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def auth_headers() -> dict[str, str]:
    return {"X-CNP-Node-Token": os.environ["BOOTSTRAP_TOKEN"]}


def admin_headers() -> dict[str, str]:
    return {"X-CNP-Admin-Token": os.environ["ADMIN_TOKEN"]}


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_hello_envelope(
    node_id: str = "cnp-test-01",
    node_name: str = "Test Node",
    zone: str = "lab",
) -> dict:
    return {
        "protocol_version": "CNPv1",
        "message_type": "hello",
        "message_id": str(uuid.uuid4()),
        "node_id": node_id,
        "ts_utc": _now_utc(),
        "qos": 1,
        "payload": {
            "device_uid": "abc123def456",
            "node_name": node_name,
            "node_type": "sensor",
            "firmware_version": "1.0.0",
            "hardware_model": "esp32-c3-supermini",
            "supports_ota": True,
            "boot_reason": "power_on",
            "capabilities": {
                "sensors": ["temperature"],
                "actuators": [],
                "connectivity": ["wifi"],
            },
        },
    }


def make_heartbeat_envelope(
    node_id: str = "cnp-test-01",
    queue_depth: int = 0,
    wifi_rssi: int = -60,
) -> dict:
    return {
        "protocol_version": "CNPv1",
        "message_type": "heartbeat",
        "message_id": str(uuid.uuid4()),
        "node_id": node_id,
        "ts_utc": _now_utc(),
        "qos": 1,
        "payload": {
            "seq": 1,
            "uptime_sec": 120,
            "free_heap_bytes": 100_000,
            "wifi_rssi": wifi_rssi,
            "queue_depth": queue_depth,
            "status": "online",
        },
    }


def make_event_envelope(
    node_id: str = "cnp-test-01",
    priority: str = "normal",
    category: str = "telemetry",
) -> dict:
    return {
        "protocol_version": "CNPv1",
        "message_type": "event",
        "message_id": str(uuid.uuid4()),
        "node_id": node_id,
        "ts_utc": _now_utc(),
        "qos": 1,
        "payload": {
            "event_type": "temperature_reading",
            "category": category,
            "priority": priority,
            "delivery_mode": "fire_and_forget",
            "requires_ack": False,
            "event_seq": 1,
            "body": {"temperature_c": 24.5},
        },
    }


async def seed_node(db_path: str, node_id: str = "cnp-test-01") -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO nodes (
                node_id, device_uid, node_name, node_type, protocol_version,
                firmware_version, hardware_model, capabilities_json,
                status, first_seen_utc, last_seen_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id, "abc123", "Test Node", "sensor", "CNPv1",
                "1.0.0", "esp32-c3-supermini", "{}",
                "online", _now_utc(), _now_utc(),
            ),
        )
        await db.commit()
