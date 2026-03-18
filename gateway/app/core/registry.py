from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .db import db_connect


async def upsert_node(db_path: str, envelope: dict[str, Any]) -> None:
    payload = envelope["payload"]
    now = envelope["ts_utc"]
    async with db_connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO nodes (
                node_id,
                device_uid,
                node_name,
                node_type,
                protocol_version,
                firmware_version,
                hardware_model,
                capabilities_json,
                status,
                first_seen_utc,
                last_seen_utc,
                boot_reason,
                heartbeat_interval_sec,
                offline_after_sec,
                supports_ota
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                device_uid=excluded.device_uid,
                node_name=excluded.node_name,
                node_type=excluded.node_type,
                protocol_version=excluded.protocol_version,
                firmware_version=excluded.firmware_version,
                hardware_model=excluded.hardware_model,
                capabilities_json=excluded.capabilities_json,
                status='online',
                last_seen_utc=excluded.last_seen_utc,
                boot_reason=excluded.boot_reason,
                supports_ota=excluded.supports_ota
            """,
            (
                envelope["node_id"],
                payload["device_uid"],
                payload["node_name"],
                payload["node_type"],
                envelope["protocol_version"],
                payload["firmware_version"],
                payload["hardware_model"],
                json.dumps(payload["capabilities"]),
                "online",
                now,
                now,
                payload.get("boot_reason", "unknown"),
                60,
                180,
                1 if payload.get("supports_ota") else 0,
            ),
        )
        await db.commit()


async def update_heartbeat(db_path: str, envelope: dict[str, Any]) -> None:
    payload = envelope["payload"]
    async with db_connect(db_path) as db:
        await db.execute(
            """
            UPDATE nodes
            SET
                status = ?,
                last_seen_utc = ?,
                last_rssi = ?,
                battery_pct = ?,
                free_heap_bytes = ?,
                queue_depth = ?
            WHERE node_id = ?
            """,
            (
                payload.get("status", "online"),
                envelope["ts_utc"],
                payload.get("wifi_rssi"),
                payload.get("battery_pct"),
                payload.get("free_heap_bytes"),
                payload.get("queue_depth", 0),
                envelope["node_id"],
            ),
        )
        await db.commit()


async def mark_offline_nodes(db_path: str, offline_after_sec: int) -> int:
    now = datetime.now(timezone.utc)
    updated = 0
    async with db_connect(db_path) as db:
        async with db.execute(
            "SELECT node_id, last_seen_utc FROM nodes WHERE status != 'retired'"
        ) as cur:
            rows = await cur.fetchall()
        for node_id, last_seen in rows:
            if not last_seen:
                continue
            seen = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            if (now - seen).total_seconds() > offline_after_sec:
                await db.execute(
                    "UPDATE nodes SET status='offline' WHERE node_id=?",
                    (node_id,),
                )
                updated += 1
        await db.commit()
    return updated
