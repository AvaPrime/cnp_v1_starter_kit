"""
CNP-OPS-004 — Heartbeat Daily Summary Aggregation.

Background task that runs every hour and rolls up the previous
24 hours of heartbeat data per node into heartbeat_daily_summary.
Also triggers node score recomputation after each rollup.

Design: append-only rollup. Each run inserts or replaces the
current day's summary. Does not delete raw heartbeats (that
is the responsibility of the trim trigger in node_registry.sql).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from .db import upsert_daily_summary
from .models import HeartbeatDailySummaryRecord
from .scoring import compute_node_score

log = logging.getLogger("cnp.ops.summaries")

_AGGREGATION_INTERVAL_SEC = 3600  # run every hour


async def _aggregate_node_day(
    db_path: str, node_id: str, day_utc: str
) -> HeartbeatDailySummaryRecord | None:
    """
    Aggregate heartbeat rows for a single node and day.
    day_utc format: YYYY-MM-DD
    """
    day_start = f"{day_utc}T00:00:00Z"
    day_end   = f"{day_utc}T23:59:59Z"

    async with aiosqlite.connect(db_path) as db:
        # Aggregate from heartbeats table
        async with db.execute(
            """
            SELECT
                COUNT(*) AS sample_count,
                MIN(free_heap_bytes)  AS min_free_heap,
                MAX(free_heap_bytes)  AS max_free_heap,
                AVG(CAST(free_heap_bytes AS REAL)) AS avg_free_heap,
                MIN(wifi_rssi)  AS min_rssi,
                MAX(wifi_rssi)  AS max_rssi,
                AVG(CAST(wifi_rssi AS REAL)) AS avg_rssi,
                MIN(COALESCE(queue_depth, 0)) AS min_queue,
                MAX(COALESCE(queue_depth, 0)) AS max_queue,
                AVG(CAST(COALESCE(queue_depth, 0) AS REAL)) AS avg_queue,
                COUNT(*) AS hb_count
            FROM heartbeats
            WHERE node_id = ?
              AND received_at BETWEEN ? AND ?
            """,
            (node_id, day_start, day_end),
        ) as cur:
            row = dict(await cur.fetchone() or {})

        # Count offline transitions from the nodes status log
        # We proxy this from ops_anomalies (offline_flapping events per node per day)
        async with db.execute(
            """
            SELECT COUNT(*) FROM ops_anomalies
            WHERE node_id = ?
              AND anomaly_type = 'offline_flapping'
              AND detected_ts_utc BETWEEN ? AND ?
            """,
            (node_id, day_start, day_end),
        ) as cur:
            transition_result = await cur.fetchone()
            offline_transitions = int(transition_result[0]) if transition_result else 0

    sample_count = int(row.get("sample_count") or 0)
    if sample_count == 0:
        return None

    def _safe_int(v: Any) -> int | None:
        return int(v) if v is not None else None

    def _safe_float(v: Any) -> float | None:
        return round(float(v), 2) if v is not None else None

    return HeartbeatDailySummaryRecord(
        node_id=node_id,
        day_utc=day_utc,
        min_free_heap_bytes=_safe_int(row.get("min_free_heap")),
        max_free_heap_bytes=_safe_int(row.get("max_free_heap")),
        avg_free_heap_bytes=_safe_float(row.get("avg_free_heap")),
        min_wifi_rssi=_safe_int(row.get("min_rssi")),
        max_wifi_rssi=_safe_int(row.get("max_rssi")),
        avg_wifi_rssi=_safe_float(row.get("avg_rssi")),
        min_queue_depth=_safe_int(row.get("min_queue")),
        max_queue_depth=_safe_int(row.get("max_queue")),
        avg_queue_depth=_safe_float(row.get("avg_queue")),
        offline_transitions=offline_transitions,
        heartbeat_count=int(row.get("hb_count") or 0),
        sample_count=sample_count,
    )


async def _get_all_node_ids(db_path: str) -> list[str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT node_id FROM nodes WHERE status != 'retired'"
        ) as cur:
            return [r[0] for r in await cur.fetchall()]


async def _get_node_row(db_path: str, node_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM nodes WHERE node_id=?", (node_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def run_daily_aggregation(db_path: str) -> int:
    """
    Aggregate yesterday + today for all non-retired nodes.
    Recomputes node health scores after each node's rollup.
    Returns number of nodes processed.
    """
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now.replace(hour=0, minute=0, second=0) -
                 __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")

    node_ids = await _get_all_node_ids(db_path)
    processed = 0

    for node_id in node_ids:
        for day in (yesterday, today):
            try:
                record = await _aggregate_node_day(db_path, node_id, day)
                if record:
                    await upsert_daily_summary(db_path, record)
            except Exception as exc:
                log.error(
                    "Aggregation failed for node=%s day=%s: %s",
                    node_id, day, exc,
                )

        # Recompute score after rollup
        try:
            node = await _get_node_row(db_path, node_id)
            if node:
                await compute_node_score(db_path, node_id, node)
        except Exception as exc:
            log.error("Score recomputation failed for node=%s: %s", node_id, exc)

        processed += 1

    log.info("[SUMMARIES] Aggregation complete — %d nodes processed", processed)
    return processed


class SummaryService:
    """
    Background task that runs daily aggregation on a fixed interval.
    Start via `asyncio.create_task(service.run())`.
    """

    def __init__(
        self,
        db_path: str,
        interval_sec: int = _AGGREGATION_INTERVAL_SEC,
    ) -> None:
        self._db_path = db_path
        self._interval = interval_sec

    async def run(self) -> None:
        log.info(
            "SummaryService started — interval=%ds", self._interval
        )
        while True:
            try:
                await run_daily_aggregation(self._db_path)
            except Exception as exc:
                log.exception("Aggregation run failed: %s", exc)
            await asyncio.sleep(self._interval)
