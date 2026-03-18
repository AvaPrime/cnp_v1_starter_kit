from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest

from app.ops.detector import AnomalyDetector
from app.ops.scoring import ScoreCalculator


async def seed_node(db_path: str, node_id: str = "node-1"):
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO nodes(
                node_id, device_uid, node_name, node_type, protocol_version, firmware_version,
                hardware_model, capabilities_json, status, first_seen_utc, last_seen_utc,
                metadata_json
            ) VALUES (?, ?, ?, ?, 'CNPv1', '1.0.0', 'esp32-c3', '{}', 'online', ?, ?, ?)
            """,
            (
                node_id,
                "dev-1",
                "Node 1",
                "sensor",
                "2026-03-18T10:00:00Z",
                "2026-03-18T10:00:00Z",
                json.dumps({"zone": "lab"}),
            ),
        )
        await db.commit()


async def add_heartbeat(db_path: str, node_id: str, idx: int, *, queue=0, heap=1000, rssi=-60, status="online"):
    ts = (datetime(2026, 3, 18, 10, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=idx)).isoformat().replace("+00:00", "Z")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO heartbeats(message_id, node_id, ts_utc, status, wifi_rssi, battery_pct, free_heap_bytes, queue_depth, dead_letter_count, body_json)
            VALUES (?, ?, ?, ?, ?, 90, ?, ?, 0, ?)
            """,
            (
                f"hb-{idx}",
                node_id,
                ts,
                status,
                rssi,
                heap,
                queue,
                json.dumps({"queue_depth": queue, "free_heap_bytes": heap, "wifi_rssi": rssi}),
            ),
        )
        await db.execute(
            "UPDATE nodes SET last_seen_utc=?, queue_depth=?, free_heap_bytes=?, last_rssi=?, status=? WHERE node_id=?",
            (ts, queue, heap, rssi, status, node_id),
        )
        await db.commit()


async def add_command(db_path: str, node_id: str, idx: int, *, latency_ms: int):
    issued = datetime(2026, 3, 18, 10, idx, 0, tzinfo=timezone.utc)
    completed = issued + timedelta(milliseconds=latency_ms)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO commands(command_id, node_id, command_type, category, issued_by, issued_ts_utc, status, timeout_ms, arguments_json, completed_ts_utc)
            VALUES (?, ?, 'set_relay', 'control', 'tester', ?, 'executed', 60000, '{}', ?)
            """,
            (
                f"cmd-{idx}",
                node_id,
                issued.isoformat().replace("+00:00", "Z"),
                completed.isoformat().replace("+00:00", "Z"),
            ),
        )
        await db.commit()


async def add_transition(db_path: str, node_id: str, idx: int, event_type: str):
    ts = (datetime(2026, 3, 18, 10, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=idx)).isoformat().replace("+00:00", "Z")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO fleet_events(event_id, node_id, zone, event_type, reason, ts_utc, body_json)
            VALUES (?, ?, 'lab', ?, 'test', ?, '{}')
            """,
            (f"fe-{idx}-{event_type}", node_id, event_type, ts),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_rule_a001_queue_congestion(initialized_db: str):
    await seed_node(initialized_db)
    for idx, q in enumerate([11, 12, 13], start=1):
        await add_heartbeat(initialized_db, "node-1", idx, queue=q)
    detector = AnomalyDetector()
    anomalies = await detector.detect_node_anomalies(initialized_db, "node-1", now_ts_utc="2026-03-18T10:05:00Z")
    assert any(a.source_rule_id == "A-001" for a in anomalies)


@pytest.mark.asyncio
async def test_rule_a002_memory_leak(initialized_db: str):
    await seed_node(initialized_db)
    for idx, heap in enumerate([1200, 1100, 1000, 900], start=1):
        await add_heartbeat(initialized_db, "node-1", idx, heap=heap)
    detector = AnomalyDetector()
    anomalies = await detector.detect_node_anomalies(initialized_db, "node-1", now_ts_utc="2026-03-18T10:05:00Z")
    assert any(a.source_rule_id == "A-002" for a in anomalies)


@pytest.mark.asyncio
async def test_rule_a003_weak_connectivity(initialized_db: str):
    await seed_node(initialized_db)
    for idx, rssi in enumerate([-82, -85, -86, -84], start=1):
        await add_heartbeat(initialized_db, "node-1", idx, rssi=rssi)
    detector = AnomalyDetector()
    anomalies = await detector.detect_node_anomalies(initialized_db, "node-1", now_ts_utc="2026-03-18T10:05:00Z")
    assert any(a.source_rule_id == "A-003" for a in anomalies)


@pytest.mark.asyncio
async def test_rule_a004_command_lag(initialized_db: str):
    await seed_node(initialized_db)
    for idx, latency in enumerate([7000, 8000, 9000], start=1):
        await add_command(initialized_db, "node-1", idx, latency_ms=latency)
    detector = AnomalyDetector()
    anomalies = await detector.detect_node_anomalies(initialized_db, "node-1", now_ts_utc="2026-03-18T10:05:00Z")
    assert any(a.source_rule_id == "A-004" for a in anomalies)


@pytest.mark.asyncio
async def test_rule_a005_offline_flapping(initialized_db: str):
    await seed_node(initialized_db)
    for idx, event_type in enumerate(["node_online", "node_offline", "node_online", "node_offline"], start=1):
        await add_transition(initialized_db, "node-1", idx, event_type)
    detector = AnomalyDetector()
    anomalies = await detector.detect_node_anomalies(initialized_db, "node-1", now_ts_utc="2026-03-18T10:08:00Z")
    assert any(a.source_rule_id == "A-005" for a in anomalies)


@pytest.mark.asyncio
async def test_score_calculator_returns_weighted_scores(initialized_db: str):
    await seed_node(initialized_db)
    for idx, q in enumerate([2, 3, 4], start=1):
        await add_heartbeat(initialized_db, "node-1", idx, queue=q, heap=1200 - (idx * 10), rssi=-65)
    calc = ScoreCalculator()
    score = await calc.calculate_node_score(initialized_db, "node-1")
    assert 0 <= score.health_score <= 100
    assert score.scope_type == "node"
    assert "queue_penalty" in score.evidence
