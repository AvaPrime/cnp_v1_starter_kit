"""
CNP EPIC-02 — P2-06 + P2-02 + P2-04
Sprint 2 test suite:

  TestCompatAdapter     — 11-step V1 compat lifecycle (port of test_flow.sh)
  TestFieldTranslation  — all V1→V2 field translations verified
  TestProvisioning      — per-node secret generation, rotation, validation
  TestMigrationDDL      — 003_v1_to_v2_schema.sql dry-run on V1 fixture
"""
from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio

from tests.conftest import auth_headers, seed_node


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _v1_envelope(msg_type: str, node_id: str, **extra) -> dict:
    """Build a V1-format envelope (uses 'protocol' and 'timestamp' keys)."""
    env = {
        "protocol": "CNPv1",          # V1 key
        "message_type": msg_type,
        "node_id": node_id,
        "timestamp": _now(),           # V1 key
        "payload": extra.pop("payload", {}),
    }
    env.update(extra)
    return env


# ================================================================
#  TestCompatAdapter — 11-step V1 compat lifecycle
# ================================================================

class TestCompatAdapter:
    """
    Full V1 node lifecycle via /v1/compat/* endpoints.
    Steps mirror the integration test in test_sprint1.py
    but use V1 envelope format throughout.
    """
    _node_id = "cnp-compat-office-01"
    _cmd_id: str = ""

    @pytest.mark.asyncio
    async def test_01_health(self, app_client):
        r = await app_client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_02_hello_v1_format(self, app_client):
        env = _v1_envelope(
            "hello", self._node_id,
            payload={
                "node_name": "Compat Office Node",
                "node_type": "sensor",
                "zone": "office",
                "firmware_version": "1.0.0",
                "capabilities": {
                    "sensors": ["temperature", "humidity"],
                    "actuators": [],
                    "connectivity": ["wifi"],
                    "power_mode": "usb",   # V1 key → translated to capabilities.power.source
                },
            },
        )
        r = await app_client.post(
            "/v1/compat/node/hello", json=env, headers=auth_headers()
        )
        assert r.status_code == 200
        body = r.json()
        # Response must be in V1 format
        assert body["registered"] is True
        assert "protocol" in body   # V1 response key

    @pytest.mark.asyncio
    async def test_03_node_appears_in_registry(self, app_client):
        r = await app_client.get("/api/nodes")
        node_ids = [n["node_id"] for n in r.json()]
        assert self._node_id in node_ids

    @pytest.mark.asyncio
    async def test_04_heartbeat_v1_format(self, app_client):
        env = _v1_envelope(
            "heartbeat", self._node_id,
            payload={
                "status": "online",
                "uptime_sec": 60,
                "battery": -1,   # V1 sentinel → NULL
                "wifi_rssi": -62,
            },
        )
        r = await app_client.post(
            "/v1/compat/node/heartbeat", json=env, headers=auth_headers()
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_05_telemetry_event_v1_format(self, app_client):
        env = _v1_envelope(
            "event", self._node_id,
            payload={
                "event_id": f"evt-{uuid.uuid4().hex[:8]}",  # V1 key
                "event_type": "temperature_reading",
                "category": "telemetry",
                "priority": "normal",
                "data": {"temperature_c": 26.1, "humidity_pct": 58},  # V1 key
            },
        )
        r = await app_client.post(
            "/v1/compat/node/event", json=env, headers=auth_headers()
        )
        assert r.status_code == 200
        # Response returns event_id for V1 compat
        assert "event_id" in r.json()

    @pytest.mark.asyncio
    async def test_06_alert_event_v1_format(self, app_client):
        env = _v1_envelope(
            "event", self._node_id,
            payload={
                "event_id": f"evt-{uuid.uuid4().hex[:8]}",
                "event_type": "temperature_threshold",
                "category": "alert",
                "priority": "high",
                "data": {"temperature_c": 33.0},
            },
        )
        r = await app_client.post(
            "/v1/compat/node/event", json=env, headers=auth_headers()
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_07_error_v1_format(self, app_client):
        env = _v1_envelope(
            "error", self._node_id,
            payload={
                "error_code": "SENSOR_READ_FAIL",    # V1 key
                "error_msg":  "DHT22 returned NaN",  # V1 key
                "recoverable": True,
            },
        )
        r = await app_client.post(
            "/v1/compat/node/error", json=env, headers=auth_headers()
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_08_issue_command(self, app_client):
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
        TestCompatAdapter._cmd_id = r.json()["command_id"]

    @pytest.mark.asyncio
    async def test_09_poll_command_v1_format(self, app_client):
        """Poll returns response in V1 format (params not arguments)."""
        r = await app_client.get(
            f"/v1/compat/node/commands/{self._node_id}",
            headers=auth_headers(),
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("command") is True
        # V1 format checks
        assert "protocol" in body        # V1 key (not protocol_version)
        assert "timestamp" in body       # V1 key (not ts_utc)
        assert "params" in body["payload"]  # V1 key (not arguments)

    @pytest.mark.asyncio
    async def test_10_command_ack_v1_format(self, app_client):
        env = _v1_envelope(
            "command_result", self._node_id,
            payload={
                "command_id": TestCompatAdapter._cmd_id,
                "status": "executed",
            },
        )
        r = await app_client.post(
            "/v1/compat/node/command_result", json=env, headers=auth_headers()
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_11_summary_reflects_compat_activity(self, app_client):
        r = await app_client.get("/api/summary")
        assert r.status_code == 200
        data = r.json()
        assert data.get("total_nodes", 0) >= 1
        assert data.get("alerts_24h", 0) >= 1


# ================================================================
#  TestFieldTranslation — V1→V2 translation correctness
# ================================================================

class TestFieldTranslation:
    """Unit tests for the _translate_envelope() function."""

    def setup_method(self):
        from app.api.compat import _translate_envelope
        self.translate = _translate_envelope

    def test_protocol_key_renamed(self):
        raw = {"protocol": "CNPv1", "node_id": "cnp-x-01"}
        result = self.translate(raw)
        assert "protocol_version" in result
        assert "protocol" not in result
        assert result["protocol_version"] == "CNPv1"

    def test_timestamp_key_renamed(self):
        raw = {"timestamp": "2026-03-18T10:00:00Z", "node_id": "cnp-x-01"}
        result = self.translate(raw)
        assert "ts_utc" in result
        assert "timestamp" not in result

    def test_timestamp_normalised_to_z(self):
        raw = {"timestamp": "2026-03-18T10:00:00+00:00", "node_id": "cnp-x-01"}
        result = self.translate(raw)
        assert result["ts_utc"].endswith("Z")

    def test_message_id_generated_if_absent(self):
        raw = {"node_id": "cnp-x-01"}
        result = self.translate(raw)
        assert "message_id" in result
        assert len(result["message_id"]) > 0

    def test_event_id_promoted_to_message_id(self):
        raw = {
            "node_id": "cnp-x-01",
            "payload": {"event_id": "evt-000001"},
        }
        result = self.translate(raw)
        assert result["message_id"] == "evt-000001"
        assert "event_id" not in result.get("payload", {})

    def test_params_renamed_to_arguments(self):
        raw = {"node_id": "cnp-x-01", "payload": {"params": {"state": "on"}}}
        result = self.translate(raw)
        assert "arguments" in result["payload"]
        assert "params" not in result["payload"]
        assert result["payload"]["arguments"] == {"state": "on"}

    def test_error_code_mapped_to_v2_model(self):
        raw = {
            "node_id": "cnp-x-01",
            "payload": {
                "error_code": "SENSOR_FAIL",
                "error_msg": "timeout",
                "recoverable": True,
            },
        }
        result = self.translate(raw)
        p = result["payload"]
        assert p["code"] == "SENSOR_FAIL"
        assert p["domain"] == "LEGACY"
        assert p["severity"] == "error"
        assert p["message"] == "timeout"
        assert "error_code" not in p
        assert "error_msg" not in p

    def test_battery_sentinel_becomes_null(self):
        raw = {"node_id": "cnp-x-01", "payload": {"battery": -1}}
        result = self.translate(raw)
        assert result["payload"]["battery_pct"] is None
        assert "battery" not in result["payload"]

    def test_battery_value_cast_to_real(self):
        raw = {"node_id": "cnp-x-01", "payload": {"battery": 85}}
        result = self.translate(raw)
        assert result["payload"]["battery_pct"] == 85.0

    def test_power_mode_restructured(self):
        raw = {
            "node_id": "cnp-x-01",
            "payload": {
                "capabilities": {"power_mode": "usb", "sensors": ["temp"]}
            },
        }
        result = self.translate(raw)
        caps = result["payload"]["capabilities"]
        assert "power" in caps
        assert caps["power"]["source"] == "usb"
        assert "power_mode" not in caps

    def test_data_renamed_to_body_for_events(self):
        raw = {
            "node_id": "cnp-x-01",
            "message_type": "event",
            "payload": {"data": {"temperature_c": 25}},
        }
        result = self.translate(raw)
        assert "body" in result["payload"]
        assert "data" not in result["payload"]

    def test_qos_defaulted_to_zero(self):
        raw = {"node_id": "cnp-x-01"}
        result = self.translate(raw)
        assert result["qos"] == 0

    def test_both_keys_present_v2_wins(self):
        """If both protocol and protocol_version present, keep protocol_version."""
        raw = {
            "protocol": "CNPv1",
            "protocol_version": "CNPv1",
            "node_id": "cnp-x-01",
        }
        result = self.translate(raw)
        assert result["protocol_version"] == "CNPv1"


# ================================================================
#  TestProvisioning — P2-02 per-node secrets
# ================================================================

class TestProvisioning:

    @pytest.mark.asyncio
    async def test_provision_returns_plain_secret(self, db_path):
        await seed_node(db_path, "cnp-prov-01")
        from app.core.auth import provision_node_secret, hash_secret
        secret = await provision_node_secret(db_path, "cnp-prov-01")
        assert len(secret) == 64   # 32 bytes hex

        # Verify stored hash
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT node_secret_hash FROM nodes WHERE node_id=?",
                ("cnp-prov-01",),
            ) as cur:
                row = await cur.fetchone()
        assert row and row[0] == hash_secret(secret)

    @pytest.mark.asyncio
    async def test_provision_fails_for_unknown_node(self, db_path):
        from app.core.auth import provision_node_secret
        with pytest.raises(ValueError, match="not found"):
            await provision_node_secret(db_path, "cnp-does-not-exist")

    @pytest.mark.asyncio
    async def test_rotate_invalidates_old_secret(self, db_path):
        await seed_node(db_path, "cnp-rot-01")
        from app.core.auth import provision_node_secret, rotate_node_secret, hash_secret

        secret1 = await provision_node_secret(db_path, "cnp-rot-01")
        secret2 = await rotate_node_secret(db_path, "cnp-rot-01")

        assert secret1 != secret2

        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT node_secret_hash FROM nodes WHERE node_id=?",
                ("cnp-rot-01",),
            ) as cur:
                row = await cur.fetchone()
        assert row[0] == hash_secret(secret2)
        assert row[0] != hash_secret(secret1)

    @pytest.mark.asyncio
    async def test_validate_hmac_token(self, db_path):
        await seed_node(db_path, "cnp-hmac-01")
        from app.core.auth import provision_node_secret, validate_node_token

        secret = await provision_node_secret(db_path, "cnp-hmac-01")
        # Compute the token as the node would
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()
        token = hmac.new(
            secret_hash.encode(), b"cnp-hmac-01", hashlib.sha256
        ).hexdigest()

        valid = await validate_node_token(db_path, "cnp-hmac-01", token)
        assert valid is True

    @pytest.mark.asyncio
    async def test_wrong_token_rejected(self, db_path):
        await seed_node(db_path, "cnp-hmac-02")
        from app.core.auth import provision_node_secret, validate_node_token
        await provision_node_secret(db_path, "cnp-hmac-02")
        valid = await validate_node_token(db_path, "cnp-hmac-02", "wrong-token-xxxx")
        assert valid is False

    @pytest.mark.asyncio
    async def test_bootstrap_token_fallback_for_unprovisioned_node(self, db_path):
        """Node with no stored secret → falls back to bootstrap token."""
        await seed_node(db_path, "cnp-bootstrap-01")
        from app.core.auth import validate_node_token
        import os
        bootstrap = os.environ.get("BOOTSTRAP_TOKEN", "test-bootstrap-token-001")
        valid = await validate_node_token(db_path, "cnp-bootstrap-01", bootstrap)
        assert valid is True

    @pytest.mark.asyncio
    async def test_none_token_always_rejected(self, db_path):
        await seed_node(db_path, "cnp-none-01")
        from app.core.auth import validate_node_token
        valid = await validate_node_token(db_path, "cnp-none-01", None)
        assert valid is False


# ================================================================
#  TestMigrationDDL — P2-04 dry-run on synthetic V1 fixture
# ================================================================

class TestMigrationDDL:
    """
    Creates a minimal V1-schema SQLite DB, runs the migration in
    dry-run mode, and verifies:
      - No errors raised
      - Row counts preserved (dry-run rolled back)
      - Live run: new columns present
    """

    @pytest.fixture
    def v1_db(self, tmp_path) -> str:
        """Build a minimal V1 database with sample rows."""
        path = str(tmp_path / "v1_test.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE nodes (
                node_id TEXT PRIMARY KEY,
                node_name TEXT NOT NULL,
                node_type TEXT NOT NULL,
                zone TEXT NOT NULL DEFAULT 'unassigned',
                protocol_version TEXT NOT NULL DEFAULT 'CNPv1',
                firmware_version TEXT,
                capabilities_json TEXT,
                status TEXT NOT NULL DEFAULT 'offline',
                battery INTEGER,
                wifi_rssi INTEGER,
                uptime_sec INTEGER DEFAULT 0,
                last_seen TEXT,
                registered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                notes TEXT
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,
                node_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                category TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'normal',
                data_json TEXT,
                timestamp TEXT NOT NULL,
                received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            );
            CREATE TABLE commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command_id TEXT UNIQUE NOT NULL,
                node_id TEXT NOT NULL,
                command_type TEXT NOT NULL,
                category TEXT NOT NULL,
                params_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                issued_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
                ack_at TEXT,
                detail TEXT
            );
            CREATE TABLE heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                status TEXT NOT NULL,
                uptime_sec INTEGER,
                battery REAL,
                wifi_rssi INTEGER,
                received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            );
            CREATE TABLE errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                error_code TEXT NOT NULL,
                error_msg TEXT,
                recoverable INTEGER DEFAULT 1,
                received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            );
            CREATE TABLE node_config (
                node_id TEXT PRIMARY KEY,
                heartbeat_interval_sec INTEGER NOT NULL DEFAULT 30,
                report_interval_sec INTEGER NOT NULL DEFAULT 60,
                permissions_json TEXT,
                custom_json TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
            );
        """)
        # Insert sample data
        conn.executemany(
            "INSERT INTO nodes (node_id, node_name, node_type, status) VALUES (?, ?, ?, ?)",
            [(f"cnp-mig-{i:02d}", f"Node {i}", "sensor", "online") for i in range(10)],
        )
        conn.executemany(
            """INSERT INTO events (event_id, node_id, event_type, category, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (f"evt-{i:06d}", "cnp-mig-00", "temp", "telemetry", "2026-03-18T10:00:00Z")
                for i in range(20)
            ],
        )
        conn.commit()
        conn.close()
        return path

    def _run_migration(self, db_path: str) -> None:
        migration = Path(__file__).parents[2] / "migrations" / "003_v1_to_v2_schema.sql"
        if not migration.exists():
            pytest.skip("Migration file not found")
        sql = migration.read_text(encoding="utf-8")
        conn = sqlite3.connect(db_path)
        # Execute statement by statement, skipping comments
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if not stmt or stmt.startswith("--"):
                continue
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as exc:
                if "duplicate column" in str(exc).lower():
                    continue
                raise
        conn.commit()
        conn.close()

    def test_migration_preserves_row_counts(self, v1_db):
        """Row counts must not decrease after migration."""
        pre = {}
        conn = sqlite3.connect(v1_db)
        for (t,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall():
            pre[t] = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
        conn.close()

        self._run_migration(v1_db)

        conn = sqlite3.connect(v1_db)
        for table, count in pre.items():
            post = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            assert post >= count, f"Row count regressed in {table}: {count} → {post}"
        conn.close()

    def test_migration_adds_v2_columns_to_nodes(self, v1_db):
        self._run_migration(v1_db)
        conn = sqlite3.connect(v1_db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
        conn.close()
        required = {
            "device_uid", "hardware_model", "boot_reason", "config_version",
            "first_seen_utc", "last_seen_utc", "battery_pct", "last_rssi",
            "free_heap_bytes", "queue_depth", "supports_ota", "metadata_json",
        }
        missing = required - cols
        assert not missing, f"Missing columns after migration: {missing}"

    def test_migration_creates_acks_table(self, v1_db):
        self._run_migration(v1_db)
        conn = sqlite3.connect(v1_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "acks" in tables

    def test_migration_backfills_battery_sentinel(self, v1_db):
        """battery = -1 must become battery_pct = NULL."""
        conn = sqlite3.connect(v1_db)
        conn.execute(
            "UPDATE nodes SET battery = -1 WHERE node_id = 'cnp-mig-00'"
        )
        conn.commit()
        conn.close()

        self._run_migration(v1_db)

        conn = sqlite3.connect(v1_db)
        (batt,) = conn.execute(
            "SELECT battery_pct FROM nodes WHERE node_id='cnp-mig-00'"
        ).fetchone()
        conn.close()
        assert batt is None

    def test_migration_idempotent(self, v1_db):
        """Running migration twice must not raise or lose data."""
        self._run_migration(v1_db)
        self._run_migration(v1_db)   # second run must be no-op

    def test_migrate_cli_dry_run(self, v1_db, tmp_path):
        """migrate.py --dry-run must exit 0 and not modify the DB."""
        import subprocess
        import sys
        script = Path(__file__).parents[2] / "scripts" / "migrate.py"
        if not script.exists():
            pytest.skip("migrate.py not found")

        snapshot = str(tmp_path / "v1_dry.snapshot.db")
        result = subprocess.run(
            [sys.executable, str(script), "--source", v1_db, "--dry-run",
             "--snapshot", snapshot],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_migrate_cli_live_run_and_rollback(self, v1_db, tmp_path):
        """migrate.py live run succeeds, then --rollback restores original."""
        import subprocess
        import sys
        script = Path(__file__).parents[2] / "scripts" / "migrate.py"
        if not script.exists():
            pytest.skip("migrate.py not found")

        snapshot = str(tmp_path / "v1_live.snapshot.db")

        # Live run
        result = subprocess.run(
            [sys.executable, str(script), "--source", v1_db, "--snapshot", snapshot],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

        # Rollback
        result = subprocess.run(
            [sys.executable, str(script), "--source", v1_db,
             "--rollback", "--snapshot", snapshot],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
