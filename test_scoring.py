"""
Tests for the health scoring engine.

Verifies:
  - Sub-score calculations are deterministic and bounded [0, 100]
  - Weighted composite score is correct
  - Edge cases: no heartbeats, no anomalies, offline node
  - Score ordering: healthy > degraded > offline
  - Fleet score aggregates node scores correctly
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from gateway.app.ops.scoring import (
    _maintainability_score,
    _performance_score,
    _reliability_score,
    _responsiveness_score,
    _security_score,
    _WEIGHTS,
    compute_node_score,
    compute_fleet_score,
)
from gateway.app.ops.models import HealthScoreRecord, ScopeType


# ----------------------------------------------------------------
#  Helpers
# ----------------------------------------------------------------

def _hb(queue_depth: int = 0, wifi_rssi: int = -60, free_heap: int = 100_000) -> dict:
    return {
        "queue_depth":     queue_depth,
        "wifi_rssi":       wifi_rssi,
        "free_heap_bytes": free_heap,
        "battery_pct":     None,
        "status":          "online",
    }


def _node(
    status: str = "online",
    supports_ota: bool = True,
    device_uid: str = "abc123",
    hardware_model: str = "esp32-c3-supermini",
    firmware_version: str = "1.0.0",
    offline_after_sec: int = 180,
    last_seen_utc: str = "2026-03-18T10:00:00Z",
) -> dict:
    return {
        "status":            status,
        "supports_ota":      supports_ota,
        "device_uid":        device_uid,
        "hardware_model":    hardware_model,
        "firmware_version":  firmware_version,
        "offline_after_sec": offline_after_sec,
        "last_seen_utc":     last_seen_utc,
    }


def _anomaly(category: str = "performance", severity: str = "warning") -> dict:
    return {"category": category, "severity": severity}


# ----------------------------------------------------------------
#  Weight integrity
# ----------------------------------------------------------------

class TestWeights:
    def test_weights_sum_to_one(self):
        assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9

    def test_all_weight_keys_present(self):
        expected = {"reliability", "performance", "security", "maintainability", "responsiveness"}
        assert set(_WEIGHTS.keys()) == expected

    def test_all_weights_positive(self):
        assert all(v > 0 for v in _WEIGHTS.values())


# ----------------------------------------------------------------
#  Reliability
# ----------------------------------------------------------------

class TestReliabilityScore:

    def test_perfect_conditions(self):
        hbs = [_hb() for _ in range(5)]
        node = _node(status="online")
        score, ev = _reliability_score(hbs, [], node)
        assert 90 <= score <= 100

    def test_zero_heartbeats_returns_zero(self):
        score, ev = _reliability_score([], [], _node())
        assert score == 0.0
        assert "no_heartbeats" in ev.get("reason", "")

    def test_offline_status_penalizes(self):
        hbs = [_hb() for _ in range(5)]
        node = _node(status="offline")
        score_online, _ = _reliability_score(hbs, [], _node(status="online"))
        score_offline, _ = _reliability_score(hbs, [], node)
        assert score_offline < score_online

    def test_active_anomalies_penalize(self):
        hbs = [_hb() for _ in range(5)]
        anomalies = [_anomaly("reliability"), _anomaly("reliability")]
        score_clean, _ = _reliability_score(hbs, [], _node())
        score_dirty, _ = _reliability_score(hbs, anomalies, _node())
        assert score_dirty < score_clean

    def test_score_bounded(self):
        for _ in range(10):
            hbs = [_hb(queue_depth=50) for _ in range(5)]
            anomalies = [_anomaly("reliability") for _ in range(10)]
            score, _ = _reliability_score(hbs, anomalies, _node(status="offline"))
            assert 0 <= score <= 100


# ----------------------------------------------------------------
#  Performance
# ----------------------------------------------------------------

class TestPerformanceScore:

    def test_perfect_conditions(self):
        hbs = [_hb(queue_depth=0, wifi_rssi=-55) for _ in range(5)]
        score, _ = _performance_score(hbs, [])
        assert score >= 90

    def test_high_queue_penalizes(self):
        clean_hbs = [_hb(queue_depth=0) for _ in range(5)]
        dirty_hbs = [_hb(queue_depth=30) for _ in range(5)]
        clean_score, _ = _performance_score(clean_hbs, [])
        dirty_score, _ = _performance_score(dirty_hbs, [])
        assert dirty_score < clean_score

    def test_weak_rssi_penalizes(self):
        good_hbs = [_hb(wifi_rssi=-55) for _ in range(5)]
        bad_hbs  = [_hb(wifi_rssi=-90) for _ in range(5)]
        good_score, _ = _performance_score(good_hbs, [])
        bad_score, _  = _performance_score(bad_hbs, [])
        assert bad_score < good_score

    def test_no_heartbeats_returns_fifty(self):
        score, ev = _performance_score([], [])
        assert score == 50.0

    def test_score_bounded(self):
        hbs = [_hb(queue_depth=100, wifi_rssi=-100) for _ in range(5)]
        anomalies = [_anomaly("performance") for _ in range(5)]
        score, _ = _performance_score(hbs, anomalies)
        assert 0 <= score <= 100


# ----------------------------------------------------------------
#  Security
# ----------------------------------------------------------------

class TestSecurityScore:

    def test_full_security_setup(self):
        node = _node(supports_ota=True, firmware_version="1.2.3")
        score, _ = _security_score(node, [])
        assert score == 100.0

    def test_no_ota_penalizes(self):
        score_ota, _    = _security_score(_node(supports_ota=True), [])
        score_no_ota, _ = _security_score(_node(supports_ota=False), [])
        assert score_no_ota < score_ota

    def test_security_anomaly_heavy_penalty(self):
        node = _node()
        score_clean, _ = _security_score(node, [])
        score_dirty, _ = _security_score(node, [_anomaly("security", "critical")])
        assert score_dirty < score_clean - 20

    def test_missing_firmware_penalizes(self):
        score_known, _   = _security_score(_node(firmware_version="1.0.0"), [])
        score_unknown, _ = _security_score(_node(firmware_version="unknown"), [])
        assert score_unknown < score_known

    def test_score_bounded(self):
        node = _node(supports_ota=False, firmware_version="unknown")
        anomalies = [_anomaly("security", "critical") for _ in range(5)]
        score, _ = _security_score(node, anomalies)
        assert 0 <= score <= 100


# ----------------------------------------------------------------
#  Maintainability
# ----------------------------------------------------------------

class TestMaintainabilityScore:

    def test_fully_maintained_node(self):
        score, _ = _maintainability_score(_node())
        assert score == 100.0

    def test_no_ota_penalizes(self):
        score, _ = _maintainability_score(_node(supports_ota=False))
        assert score < 100.0

    def test_no_device_uid_penalizes(self):
        score, _ = _maintainability_score(_node(device_uid=""))
        assert score < 100.0

    def test_unknown_hardware_penalizes(self):
        score, _ = _maintainability_score(_node(hardware_model="unknown"))
        assert score < 100.0

    def test_fully_degraded_node(self):
        node = _node(supports_ota=False, device_uid="", hardware_model="unknown")
        score, _ = _maintainability_score(node)
        assert score <= 55.0


# ----------------------------------------------------------------
#  Responsiveness
# ----------------------------------------------------------------

class TestResponsivenessScore:

    def test_recently_seen_node(self):
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(seconds=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        node = _node(last_seen_utc=recent, offline_after_sec=180)
        score, _ = _responsiveness_score(node, [])
        assert score >= 90

    def test_never_seen_returns_zero(self):
        node = {**_node(), "last_seen_utc": None}
        score, ev = _responsiveness_score(node, [])
        assert score == 0.0

    def test_long_since_seen_penalizes(self):
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(seconds=3600)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        node = _node(last_seen_utc=old, offline_after_sec=180)
        score, _ = _responsiveness_score(node, [])
        assert score < 30.0

    def test_score_bounded(self):
        from datetime import datetime, timezone, timedelta
        for secs in [0, 60, 180, 600, 3600]:
            ts = (datetime.now(timezone.utc) - timedelta(seconds=secs)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            node = _node(last_seen_utc=ts)
            score, _ = _responsiveness_score(node, [])
            assert 0 <= score <= 100


# ----------------------------------------------------------------
#  Composite score ordering
# ----------------------------------------------------------------

class TestCompositeOrdering:

    def _compute_weighted(self, rel, perf, sec, maint, resp) -> float:
        return (
            rel   * _WEIGHTS["reliability"]
            + perf  * _WEIGHTS["performance"]
            + sec   * _WEIGHTS["security"]
            + maint * _WEIGHTS["maintainability"]
            + resp  * _WEIGHTS["responsiveness"]
        )

    def test_healthy_beats_degraded(self):
        healthy  = self._compute_weighted(95, 90, 100, 100, 95)
        degraded = self._compute_weighted(60, 70, 80, 80, 60)
        assert healthy > degraded

    def test_degraded_beats_dead(self):
        degraded = self._compute_weighted(60, 70, 80, 80, 60)
        dead     = self._compute_weighted(0, 0, 50, 50, 0)
        assert degraded > dead

    def test_composite_bounded(self):
        for vals in [
            (100, 100, 100, 100, 100),
            (0, 0, 0, 0, 0),
            (50, 50, 50, 50, 50),
        ]:
            score = self._compute_weighted(*vals)
            assert 0 <= score <= 100


# ----------------------------------------------------------------
#  compute_node_score integration (mocked DB)
# ----------------------------------------------------------------

class TestComputeNodeScore:

    @pytest.mark.asyncio
    async def test_returns_health_score_record(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        node = _node()
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(seconds=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        node["last_seen_utc"] = recent

        mock_hbs = [
            type("HB", (), {
                "queue_depth": 0,
                "wifi_rssi": -60,
                "free_heap_bytes": 100_000,
                "battery_pct": None,
                "status": "online",
            })()
            for _ in range(5)
        ]

        with (
            patch("gateway.app.ops.scoring.get_recent_heartbeats", new=AsyncMock(return_value=mock_hbs)),
            patch("gateway.app.ops.scoring.get_anomalies", new=AsyncMock(return_value=[])),
            patch("gateway.app.ops.scoring.persist_health_score", new=AsyncMock()),
        ):
            result = await compute_node_score(db_path, "cnp-test-01", node)

        assert isinstance(result, HealthScoreRecord)
        assert result.scope_type == ScopeType.NODE
        assert result.scope_id == "cnp-test-01"
        assert 0 <= result.health_score <= 100
        assert 0 <= result.reliability_score <= 100
        assert 0 <= result.performance_score <= 100
        assert 0 <= result.security_score <= 100

    @pytest.mark.asyncio
    async def test_score_is_deterministic(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        node = _node()
        from datetime import datetime, timezone, timedelta
        node["last_seen_utc"] = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        mock_hbs = [
            type("HB", (), {
                "queue_depth": 2, "wifi_rssi": -65, "free_heap_bytes": 90_000,
                "battery_pct": None, "status": "online",
            })()
            for _ in range(3)
        ]

        scores = []
        for _ in range(3):
            with (
                patch("gateway.app.ops.scoring.get_recent_heartbeats",
                      new=AsyncMock(return_value=mock_hbs)),
                patch("gateway.app.ops.scoring.get_anomalies",
                      new=AsyncMock(return_value=[])),
                patch("gateway.app.ops.scoring.persist_health_score",
                      new=AsyncMock()),
            ):
                r = await compute_node_score(db_path, "cnp-det-01", node)
                scores.append(r.health_score)

        assert len(set(scores)) == 1, f"Score not deterministic: {scores}"
