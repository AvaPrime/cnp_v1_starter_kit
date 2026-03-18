from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import aiosqlite


async def _insert_fleet_event(
    db: aiosqlite.Connection,
    *,
    node_id: str | None,
    zone: str | None,
    event_type: str,
    reason: str,
    ts_utc: str,
    body: dict[str, Any],
) -> None:
    await db.execute(
        """
        INSERT INTO fleet_events(event_id, node_id, zone, event_type, reason, ts_utc, body_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (str(uuid4()), node_id, zone, event_type, reason, ts_utc, json.dumps(body)),
    )


async def upsert_node(db_path: str, envelope: dict[str, Any]) -> None:
    payload = envelope["payload"]
    now = envelope["ts_utc"]
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT status, metadata_json FROM nodes WHERE node_id=?",
            (envelope["node_id"],),
        ) as cur:
            existing = await cur.fetchone()

        metadata = {"zone": payload.get("zone", "unknown")}
        await db.execute(
            """
            INSERT INTO nodes (
                node_id, device_uid, node_name, node_type, protocol_version, firmware_version,
                hardware_model, capabilities_json, status, first_seen_utc, last_seen_utc, boot_reason,
                heartbeat_interval_sec, offline_after_sec, supports_ota, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                supports_ota=excluded.supports_ota,
                metadata_json=excluded.metadata_json
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
                payload.get("heartbeat_interval_sec", 60),
                payload.get("offline_after_sec", 180),
                1 if payload.get("supports_ota") else 0,
                json.dumps(metadata),
            ),
        )

        if existing is None or existing["status"] != "online":
            await _insert_fleet_event(
                db,
                node_id=envelope["node_id"],
                zone=metadata["zone"],
                event_type="node_online",
                reason="registration_or_recovery",
                ts_utc=now,
                body={"message_id": envelope["message_id"]},
            )
        await db.commit()


async def update_heartbeat(db_path: str, envelope: dict[str, Any]) -> None:
    payload = envelope["payload"]
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT status, metadata_json FROM nodes WHERE node_id=?",
            (envelope["node_id"],),
        ) as cur:
            existing = await cur.fetchone()
        metadata = json.loads(existing["metadata_json"]) if existing and existing["metadata_json"] else {}
        status_before = existing["status"] if existing else "unknown"

        await db.execute(
            """
            UPDATE nodes
            SET status = ?, last_seen_utc = ?, last_rssi = ?, battery_pct = ?, free_heap_bytes = ?, queue_depth = ?
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
        await db.execute(
            """
            INSERT OR IGNORE INTO heartbeats(
                message_id, node_id, ts_utc, status, wifi_rssi, battery_pct,
                free_heap_bytes, queue_depth, dead_letter_count, body_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                envelope["message_id"],
                envelope["node_id"],
                envelope["ts_utc"],
                payload.get("status", "online"),
                payload.get("wifi_rssi"),
                payload.get("battery_pct"),
                payload.get("free_heap_bytes"),
                payload.get("queue_depth", 0),
                payload.get("dead_letter_count", 0),
                json.dumps(payload),
            ),
        )
        if status_before == "offline" and payload.get("status", "online") == "online":
            await _insert_fleet_event(
                db,
                node_id=envelope["node_id"],
                zone=metadata.get("zone"),
                event_type="node_online",
                reason="heartbeat_recovery",
                ts_utc=envelope["ts_utc"],
                body={"message_id": envelope["message_id"]},
            )
        await db.commit()


async def mark_offline_nodes(db_path: str, offline_after_sec: int) -> int:
    now = datetime.now(timezone.utc)
    updated = 0
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT node_id, last_seen_utc, status, metadata_json FROM nodes WHERE status != 'retired'"
        ) as cur:
            rows = await cur.fetchall()
        for row in rows:
            node_id = row["node_id"]
            last_seen = row["last_seen_utc"]
            if not last_seen:
                continue
            seen = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            effective_timeout = offline_after_sec
            if (now - seen).total_seconds() > effective_timeout and row["status"] != "offline":
                await db.execute("UPDATE nodes SET status='offline' WHERE node_id=?", (node_id,))
                metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
                await _insert_fleet_event(
                    db,
                    node_id=node_id,
                    zone=metadata.get("zone"),
                    event_type="node_offline",
                    reason="heartbeat_timeout",
                    ts_utc=now.isoformat().replace("+00:00", "Z"),
                    body={"last_seen_utc": last_seen, "timeout_sec": effective_timeout},
                )
                updated += 1
        await db.commit()
    return updated
