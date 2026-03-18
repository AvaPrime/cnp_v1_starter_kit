from __future__ import annotations

import json
from typing import Any

from .db import db_connect


async def insert_event(db_path: str, envelope: dict[str, Any]) -> None:
    p = envelope["payload"]
    async with db_connect(db_path) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO events(
                message_id,
                node_id,
                ts_utc,
                category,
                event_type,
                priority,
                requires_ack,
                body_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                envelope["message_id"],
                envelope["node_id"],
                envelope["ts_utc"],
                p["category"],
                p["event_type"],
                p["priority"],
                1 if p["requires_ack"] else 0,
                json.dumps(p["body"]),
            ),
        )
        await db.commit()


async def insert_error(db_path: str, envelope: dict[str, Any]) -> None:
    p = envelope["payload"]
    async with db_connect(db_path) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO errors(
                message_id,
                node_id,
                ts_utc,
                severity,
                domain,
                code,
                message,
                recoverable,
                diagnostics_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                envelope["message_id"],
                envelope["node_id"],
                envelope["ts_utc"],
                p["severity"],
                p["domain"],
                p["code"],
                p["message"],
                1 if p["recoverable"] else 0,
                json.dumps(p.get("diagnostics", {})),
            ),
        )
        await db.commit()


async def insert_ack(db_path: str, envelope: dict[str, Any]) -> None:
    p = envelope["payload"]
    async with db_connect(db_path) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO acks(
                message_id,
                node_id,
                ack_type,
                target_message_id,
                result,
                reason,
                ts_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                envelope["message_id"],
                envelope["node_id"],
                p["ack_type"],
                p["target_message_id"],
                p["result"],
                p.get("reason"),
                envelope["ts_utc"],
            ),
        )
        await db.commit()


async def create_command(
    db_path: str,
    command_payload: dict[str, Any],
    node_id: str,
) -> None:
    async with db_connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO commands(
                command_id,
                node_id,
                command_type,
                category,
                issued_by,
                issued_ts_utc,
                status,
                timeout_ms,
                arguments_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                command_payload["command_id"],
                node_id,
                command_payload["command_type"],
                command_payload["category"],
                command_payload["issued_by"],
                command_payload["issued_ts_utc"],
                "queued",
                command_payload["timeout_ms"],
                json.dumps(command_payload["arguments"]),
            ),
        )
        await db.commit()


async def upsert_command_result(db_path: str, envelope: dict[str, Any]) -> None:
    p = envelope["payload"]
    async with db_connect(db_path) as db:
        await db.execute(
            """
            UPDATE commands
            SET
                status=?,
                result_code=?,
                result_details_json=?,
                completed_ts_utc=?
            WHERE command_id=?
            """,
            (
                p["status"],
                p["code"],
                json.dumps(p.get("details", {})),
                envelope["ts_utc"],
                p["command_id"],
            ),
        )
        await db.commit()
