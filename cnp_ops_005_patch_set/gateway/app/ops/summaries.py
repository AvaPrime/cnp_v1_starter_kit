from __future__ import annotations

import aiosqlite


async def refresh_heartbeat_daily_summary(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO heartbeat_daily_summary (
                node_id, day_utc,
                min_free_heap_bytes, max_free_heap_bytes, avg_free_heap_bytes,
                min_wifi_rssi, max_wifi_rssi, avg_wifi_rssi,
                min_queue_depth, max_queue_depth, avg_queue_depth,
                sample_count
            )
            SELECT
                node_id,
                substr(ts_utc, 1, 10) AS day_utc,
                MIN(free_heap_bytes),
                MAX(free_heap_bytes),
                AVG(free_heap_bytes),
                MIN(wifi_rssi),
                MAX(wifi_rssi),
                AVG(wifi_rssi),
                MIN(queue_depth),
                MAX(queue_depth),
                AVG(queue_depth),
                COUNT(*)
            FROM heartbeats
            GROUP BY node_id, substr(ts_utc, 1, 10)
            ON CONFLICT(node_id, day_utc) DO UPDATE SET
                min_free_heap_bytes=excluded.min_free_heap_bytes,
                max_free_heap_bytes=excluded.max_free_heap_bytes,
                avg_free_heap_bytes=excluded.avg_free_heap_bytes,
                min_wifi_rssi=excluded.min_wifi_rssi,
                max_wifi_rssi=excluded.max_wifi_rssi,
                avg_wifi_rssi=excluded.avg_wifi_rssi,
                min_queue_depth=excluded.min_queue_depth,
                max_queue_depth=excluded.max_queue_depth,
                avg_queue_depth=excluded.avg_queue_depth,
                sample_count=excluded.sample_count
            """
        )
        changed = db.total_changes
        await db.commit()
        return changed
