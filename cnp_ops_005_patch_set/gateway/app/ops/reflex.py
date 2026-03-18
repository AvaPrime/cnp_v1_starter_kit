from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

import aiosqlite

from ..core.storage import retire_stale_commands, set_node_degraded
from .models import AnomalyRecord, ReflexAction

log = logging.getLogger(__name__)


class ReflexEngine:
    """Maps anomalies to safe corrective actions."""

    async def plan(self, anomaly: AnomalyRecord) -> ReflexAction:
        action_type = anomaly.recommended_action or "emit_alert"
        payload: dict[str, object] = {}

        if anomaly.anomaly_type == "queue_congestion":
            action_type = "publish_config_update"
            payload = {
                "telemetry_interval_sec_multiplier": 2.0,
                "heartbeat_interval_sec_multiplier": 1.5,
            }
        elif anomaly.anomaly_type == "weak_connectivity":
            action_type = "publish_config_update"
            payload = {"low_bandwidth_mode": True, "heartbeat_interval_sec_multiplier": 2.0}
        elif anomaly.anomaly_type == "command_lag":
            action_type = "retire_stale_commands"
            payload = {"grace_minutes": 60}
        elif anomaly.anomaly_type == "offline_flapping":
            action_type = "set_node_degraded"
            payload = {"offline_after_sec_multiplier": 1.5}
        elif anomaly.anomaly_type == "memory_leak_suspected":
            action_type = "emit_alert"
            payload = {"recommended": "request_reboot_during_safe_window"}

        return ReflexAction(
            action_id=str(uuid4()),
            anomaly_id=anomaly.anomaly_id,
            node_id=anomaly.node_id,
            issued_ts_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            action_type=action_type,
            action_payload=payload,
            execution_status="planned",
            safe_mode=action_type not in {"request_reboot", "quarantine_node"},
            requires_human=action_type in {"request_reboot", "quarantine_node"},
        )

    async def persist_action(self, db_path: str, action: ReflexAction) -> None:
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                INSERT INTO ops_reflex_actions(
                    action_id, anomaly_id, issued_ts_utc, node_id, action_type,
                    action_payload_json, execution_status, result_json,
                    safe_mode, requires_human, completed_ts_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.action_id,
                    action.anomaly_id,
                    action.issued_ts_utc,
                    action.node_id,
                    action.action_type,
                    json.dumps(action.action_payload),
                    action.execution_status,
                    json.dumps(action.result) if action.result is not None else None,
                    1 if action.safe_mode else 0,
                    1 if action.requires_human else 0,
                    action.completed_ts_utc,
                ),
            )
            await db.commit()

    async def execute(self, db_path: str, action: ReflexAction) -> ReflexAction:
        if action.requires_human:
            action.execution_status = "awaiting_human"
            await self.persist_action(db_path, action)
            return action

        try:
            if action.action_type == "set_node_degraded" and action.node_id:
                await set_node_degraded(db_path, action.node_id)
            elif action.action_type == "retire_stale_commands" and action.node_id:
                retired = await retire_stale_commands(
                    db_path,
                    action.node_id,
                    int(action.action_payload.get("grace_minutes", 60)),
                )
                action.result = {"retired_count": retired}
            action.execution_status = "executed"
            action.completed_ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception as exc:  # pragma: no cover - defensive logging
            log.exception("Reflex execution failed", exc_info=exc)
            action.execution_status = "failed"
            action.result = {"error": str(exc)}
            action.completed_ts_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        await self.persist_action(db_path, action)
        return action
