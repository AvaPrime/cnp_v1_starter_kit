"""
Tests for anomaly detection rules.

Covers:
  - A-001 queue congestion trigger and suppression
  - A-002 memory leak declining trend detection
  - A-003 weak connectivity trigger
  - A-005 offline flapping detection
  - Suppression window blocks repeat firing
  - Insufficient window size does not trigger
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.app.ops.detector import AnomalyQueue, DetectorService
from gateway.app.ops.models import AnomalyCategory, AnomalySeverity, HeartbeatSnapshot


# ----------------------------------------------------------------
#  Fixtures
# ----------------------------------------------------------------

def _make_snapshot(
    node_id: str = "cnp-test-01",
    queue_depth: int = 0,
    wifi_rssi: int = -60,
    free_heap_bytes: int | None = 100_000,
    status: str = "online",
    ts_offset_sec: int = 0,
) -> HeartbeatSnapshot:
    ts = (datetime.now(timezone.utc) + timedelta(seconds=ts_offset_sec)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return HeartbeatSnapshot(
        node_id=node_id,
        ts_utc=ts,
        free_heap_bytes=free_heap_bytes,
        wifi_rssi=wifi_rssi,
        queue_depth=queue_depth,
        battery_pct=None,
        status=status,
    )


@pytest.fixture
def queue() -> AnomalyQueue:
    return AnomalyQueue(maxsize=64)


@pytest.fixture
def detector(queue: AnomalyQueue, tmp_path) -> DetectorService:
    db_path = str(tmp_path / "test.db")
    return DetectorService(db_path=db_path, anomaly_queue=queue)


# ----------------------------------------------------------------
#  A-001  Queue Congestion
# ----------------------------------------------------------------

class TestQueueCongestion:

    @pytest.mark.asyncio
    async def test_fires_after_three_consecutive_hits(self, detector, queue):
        node_id = "cnp-test-01"
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
            patch("gateway.app.ops.detector.persist_anomaly", new=AsyncMock()),
            patch("gateway.app.ops.detector.upsert_rule_state", new=AsyncMock()),
        ):
            for i in range(3):
                snap = _make_snapshot(node_id=node_id, queue_depth=15)
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a001_queue_congestion(node_id, window)

        assert queue.qsize() == 1
        anomaly = await queue.get()
        assert anomaly.anomaly_type == "queue_congestion"
        assert anomaly.category == AnomalyCategory.PERFORMANCE
        assert anomaly.severity == AnomalySeverity.WARNING
        assert anomaly.node_id == node_id
        assert anomaly.source_rule_id == "A-001"

    @pytest.mark.asyncio
    async def test_does_not_fire_below_threshold(self, detector, queue):
        node_id = "cnp-test-02"
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
            patch("gateway.app.ops.detector.persist_anomaly", new=AsyncMock()),
        ):
            for _ in range(3):
                snap = _make_snapshot(node_id=node_id, queue_depth=5)  # below 10
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a001_queue_congestion(node_id, window)

        assert queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_does_not_fire_with_insufficient_window(self, detector, queue):
        node_id = "cnp-test-03"
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
        ):
            # Only 2 snapshots — need 3
            for _ in range(2):
                snap = _make_snapshot(node_id=node_id, queue_depth=20)
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a001_queue_congestion(node_id, window)

        assert queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_suppressed_rule_does_not_fire(self, detector, queue):
        node_id = "cnp-test-04"
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=True)),
            patch("gateway.app.ops.detector.persist_anomaly", new=AsyncMock()) as mock_persist,
        ):
            for _ in range(5):
                snap = _make_snapshot(node_id=node_id, queue_depth=25)
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a001_queue_congestion(node_id, window)
            mock_persist.assert_not_called()

        assert queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_score_scales_with_queue_depth(self, detector, queue):
        node_id = "cnp-test-05"
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
            patch("gateway.app.ops.detector.persist_anomaly", new=AsyncMock()),
            patch("gateway.app.ops.detector.upsert_rule_state", new=AsyncMock()),
        ):
            for _ in range(3):
                snap = _make_snapshot(node_id=node_id, queue_depth=50)
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a001_queue_congestion(node_id, window)

        anomaly = await queue.get()
        assert anomaly.score == 1.0  # 50/50 = 1.0


# ----------------------------------------------------------------
#  A-002  Memory Leak
# ----------------------------------------------------------------

class TestMemoryLeak:

    @pytest.mark.asyncio
    async def test_fires_on_strict_decline(self, detector, queue):
        node_id = "cnp-mem-01"
        heaps = [100_000, 90_000, 80_000]  # strict decline > 5%
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
            patch("gateway.app.ops.detector.persist_anomaly", new=AsyncMock()),
            patch("gateway.app.ops.detector.upsert_rule_state", new=AsyncMock()),
        ):
            for h in heaps:
                snap = _make_snapshot(node_id=node_id, free_heap_bytes=h)
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a002_memory_leak(node_id, window)

        assert queue.qsize() == 1
        anomaly = await queue.get()
        assert anomaly.anomaly_type == "memory_leak"
        assert anomaly.evidence_json["pct_drop"] == pytest.approx(20.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_does_not_fire_on_recovery(self, detector, queue):
        node_id = "cnp-mem-02"
        heaps = [80_000, 90_000, 85_000]  # not monotone decline
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
        ):
            for h in heaps:
                snap = _make_snapshot(node_id=node_id, free_heap_bytes=h)
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a002_memory_leak(node_id, window)

        assert queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_does_not_fire_on_minor_decline(self, detector, queue):
        node_id = "cnp-mem-03"
        # < 5% total drop — not meaningful
        heaps = [100_000, 98_000, 97_000]
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
        ):
            for h in heaps:
                snap = _make_snapshot(node_id=node_id, free_heap_bytes=h)
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a002_memory_leak(node_id, window)

        assert queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_does_not_fire_with_none_heap_values(self, detector, queue):
        node_id = "cnp-mem-04"
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
        ):
            for _ in range(3):
                snap = _make_snapshot(node_id=node_id, free_heap_bytes=None)
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a002_memory_leak(node_id, window)

        assert queue.qsize() == 0


# ----------------------------------------------------------------
#  A-003  Weak Connectivity
# ----------------------------------------------------------------

class TestWeakConnectivity:

    @pytest.mark.asyncio
    async def test_fires_after_three_consecutive_weak_rssi(self, detector, queue):
        node_id = "cnp-rssi-01"
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
            patch("gateway.app.ops.detector.persist_anomaly", new=AsyncMock()),
            patch("gateway.app.ops.detector.upsert_rule_state", new=AsyncMock()),
        ):
            for _ in range(3):
                snap = _make_snapshot(node_id=node_id, wifi_rssi=-85)
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a003_weak_connectivity(node_id, window)

        assert queue.qsize() == 1
        anomaly = await queue.get()
        assert anomaly.anomaly_type == "weak_connectivity"
        assert anomaly.category == AnomalyCategory.CONNECTIVITY
        assert anomaly.evidence_json["threshold"] == -80

    @pytest.mark.asyncio
    async def test_does_not_fire_with_good_rssi(self, detector, queue):
        node_id = "cnp-rssi-02"
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
        ):
            for _ in range(3):
                snap = _make_snapshot(node_id=node_id, wifi_rssi=-65)
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a003_weak_connectivity(node_id, window)

        assert queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_mixed_rssi_does_not_fire(self, detector, queue):
        node_id = "cnp-rssi-03"
        rssi_values = [-85, -70, -88]  # mixed — not all below threshold
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
        ):
            for rssi in rssi_values:
                snap = _make_snapshot(node_id=node_id, wifi_rssi=rssi)
                detector._append_window(node_id, snap)

            window = detector.get_window(node_id)
            await detector._check_a003_weak_connectivity(node_id, window)

        assert queue.qsize() == 0


# ----------------------------------------------------------------
#  A-005  Offline Flapping
# ----------------------------------------------------------------

class TestOfflineFlapping:

    @pytest.mark.asyncio
    async def test_fires_after_three_transitions_in_window(self, detector, queue):
        node_id = "cnp-flap-01"
        now = datetime.now(timezone.utc)
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
            patch("gateway.app.ops.detector.persist_anomaly", new=AsyncMock()),
            patch("gateway.app.ops.detector.upsert_rule_state", new=AsyncMock()),
        ):
            from collections import deque
            detector._flap_log[node_id] = deque(maxlen=20)
            for i in range(4):  # 4 offline transitions
                detector._flap_log[node_id].append(
                    (now - timedelta(seconds=i * 60), "offline")
                )

            await detector._check_a005_offline_flapping(node_id, zone="office")

        assert queue.qsize() == 1
        anomaly = await queue.get()
        assert anomaly.anomaly_type == "offline_flapping"
        assert anomaly.severity == AnomalySeverity.ERROR

    @pytest.mark.asyncio
    async def test_does_not_fire_below_threshold(self, detector, queue):
        node_id = "cnp-flap-02"
        now = datetime.now(timezone.utc)
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
        ):
            from collections import deque
            detector._flap_log[node_id] = deque(maxlen=20)
            for i in range(2):  # only 2 — need 3
                detector._flap_log[node_id].append((now - timedelta(seconds=i * 60), "offline"))

            await detector._check_a005_offline_flapping(node_id, zone="office")

        assert queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_does_not_fire_for_old_transitions(self, detector, queue):
        node_id = "cnp-flap-03"
        now = datetime.now(timezone.utc)
        with (
            patch("gateway.app.ops.detector.is_suppressed", new=AsyncMock(return_value=False)),
        ):
            from collections import deque
            detector._flap_log[node_id] = deque(maxlen=20)
            for i in range(5):
                # All transitions > 600s ago (outside window)
                detector._flap_log[node_id].append(
                    (now - timedelta(seconds=700 + i * 60), "offline")
                )

            await detector._check_a005_offline_flapping(node_id, zone="office")

        assert queue.qsize() == 0


# ----------------------------------------------------------------
#  AnomalyQueue
# ----------------------------------------------------------------

class TestAnomalyQueue:

    def test_qsize_reflects_enqueued(self):
        q = AnomalyQueue(maxsize=4)
        assert q.qsize() == 0

    @pytest.mark.asyncio
    async def test_put_and_get(self):
        from gateway.app.ops.models import AnomalyRecord, AnomalyCategory, AnomalySeverity
        q = AnomalyQueue(maxsize=4)
        a = AnomalyRecord(
            node_id="cnp-x-01",
            anomaly_type="test",
            category=AnomalyCategory.PERFORMANCE,
            severity=AnomalySeverity.INFO,
            score=0.5,
            confidence=0.8,
            source_rule_id="TEST",
        )
        await q.put(a)
        assert q.qsize() == 1
        result = await q.get()
        assert result.anomaly_type == "test"

    @pytest.mark.asyncio
    async def test_full_queue_drops_gracefully(self):
        from gateway.app.ops.models import AnomalyRecord, AnomalyCategory, AnomalySeverity
        q = AnomalyQueue(maxsize=1)
        a = AnomalyRecord(
            node_id="cnp-x-02",
            anomaly_type="test",
            category=AnomalyCategory.PERFORMANCE,
            severity=AnomalySeverity.INFO,
            score=0.1,
            confidence=0.5,
            source_rule_id="TEST",
        )
        await q.put(a)  # fills queue
        await q.put(a)  # should not raise — drops silently
        assert q.qsize() == 1
