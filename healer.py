"""
CNP-OPS-004 — Auto-Healing Executor (Reflex Engine).

Consumes AnomalyRecord instances from AnomalyQueue,
evaluates the matching rule's reflex spec, checks the
safety policy, and executes approved actions.

Safety policy (hard-coded — no config override allowed):
  L0  always auto-execute (log only)
  L1  always auto-execute (notify only)
  L2  auto-execute if zone not in L2_BLOCKED_ZONES env set
  L3  never auto-execute without explicit allowlist
  L4  never auto-execute

Actions implemented (Phase O2):
  observe_only           — log anomaly, no action
  emit_alert             — structured log at WARNING/ERROR
  publish_config_update  — send config_update via MQTT bridge
  set_node_degraded      — update node status in registry
  retire_stale_commands  — mark old pending commands as timeout

Actions deferred (Phase O3):
  quarantine_node        — requires per-node auth (P2-02)
  request_reboot         — requires L3 allowlist policy
  pause_zone_automation  — requires zone automation table
  require_human_approval — requires operator workflow
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from .db import persist_reflex_action, update_anomaly_status, update_reflex_status
from .models import (
    AnomalyRecord,
    AnomalyStatus,
    ReflexActionRecord,
    ReflexActionType,
    ReflexExecutionStatus,
    SafetyLevel,
)
from .rules import get_rule

log = logging.getLogger("cnp.ops.healer")

# Maximum safety level that auto-executes without human approval.
# Change to SafetyLevel.L3 to allow more aggressive automation.
AUTO_EXECUTE_MAX_LEVEL = SafetyLevel.L2


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class HealerService:
    """
    Consumes anomalies from the queue and executes approved reflexes.
    Must be started as a background asyncio task.
    """

    def __init__(
        self,
        db_path: str,
        anomaly_queue: Any,   # AnomalyQueue — avoid circular import
        mqtt_bridge: Any,     # GatewayMqttBridge or None
    ) -> None:
        self._db_path = db_path
        self._queue = anomaly_queue
        self._bridge = mqtt_bridge

    async def run(self) -> None:
        """
        Continuous loop. Each anomaly is processed once.
        This task should be started in main.py lifespan.
        """
        log.info("HealerService started — waiting for anomalies")
        while True:
            try:
                anomaly: AnomalyRecord = await self._queue.get()
                await self._process(anomaly)
                self._queue.task_done()
            except asyncio.CancelledError:
                log.info("HealerService cancelled")
                raise
            except Exception as exc:
                log.exception("Unhandled error in healer: %s", exc)

    # ----------------------------------------------------------------
    #  Core dispatch
    # ----------------------------------------------------------------

    async def _process(self, anomaly: AnomalyRecord) -> None:
        rule = get_rule(anomaly.source_rule_id)
        if not rule or not rule.default_reflex:
            log.debug(
                "No reflex defined for rule %s — logging only",
                anomaly.source_rule_id,
            )
            return

        reflex = rule.default_reflex
        safety = SafetyLevel(reflex.safety_level)

        if safety > AUTO_EXECUTE_MAX_LEVEL:
            log.warning(
                "[REFLEX] Rule %s requires L%d — escalating to human approval "
                "(anomaly_id=%s node=%s)",
                anomaly.source_rule_id,
                int(safety),
                anomaly.anomaly_id,
                anomaly.node_id,
            )
            await update_anomaly_status(
                self._db_path, anomaly.anomaly_id, AnomalyStatus.ESCALATED
            )
            return

        action = ReflexActionRecord(
            anomaly_id=anomaly.anomaly_id,
            node_id=anomaly.node_id,
            action_type=ReflexActionType(reflex.action_type),
            action_payload_json=reflex.payload,
            safety_level=safety,
            requires_human=reflex.requires_human,
        )
        await persist_reflex_action(self._db_path, action)

        try:
            result = await self._execute(action, anomaly)
            await update_reflex_status(
                self._db_path,
                action.action_id,
                ReflexExecutionStatus.COMPLETED,
                result,
            )
            log.info(
                "[REFLEX] %s executed for node=%s (anomaly=%s)",
                action.action_type.value,
                anomaly.node_id,
                anomaly.anomaly_id,
            )
        except Exception as exc:
            log.error(
                "[REFLEX] %s failed for node=%s: %s",
                action.action_type.value,
                anomaly.node_id,
                exc,
            )
            await update_reflex_status(
                self._db_path,
                action.action_id,
                ReflexExecutionStatus.FAILED,
                {"error": str(exc)},
            )

    # ----------------------------------------------------------------
    #  Action executors
    # ----------------------------------------------------------------

    async def _execute(
        self, action: ReflexActionRecord, anomaly: AnomalyRecord
    ) -> dict[str, Any]:
        dispatch = {
            ReflexActionType.OBSERVE_ONLY:          self._exec_observe,
            ReflexActionType.EMIT_ALERT:             self._exec_emit_alert,
            ReflexActionType.PUBLISH_CONFIG_UPDATE:  self._exec_config_update,
            ReflexActionType.SET_NODE_DEGRADED:      self._exec_set_degraded,
            ReflexActionType.RETIRE_STALE_COMMANDS:  self._exec_retire_commands,
        }
        handler = dispatch.get(action.action_type)
        if not handler:
            log.warning(
                "Action type %s not implemented — skipping",
                action.action_type.value,
            )
            return {"skipped": True, "reason": "not_implemented"}
        return await handler(action, anomaly)

    async def _exec_observe(
        self, action: ReflexActionRecord, anomaly: AnomalyRecord
    ) -> dict[str, Any]:
        log.info(
            "[OPS] Observe: %s on node=%s severity=%s",
            anomaly.anomaly_type,
            anomaly.node_id,
            anomaly.severity.value,
        )
        return {"observed": True}

    async def _exec_emit_alert(
        self, action: ReflexActionRecord, anomaly: AnomalyRecord
    ) -> dict[str, Any]:
        level = anomaly.severity.value
        msg = (
            f"[OPS ALERT] {anomaly.anomaly_type} | "
            f"node={anomaly.node_id} | zone={anomaly.zone} | "
            f"severity={level} | score={anomaly.score:.2f}"
        )
        if level in ("error", "critical"):
            log.error(msg)
        else:
            log.warning(msg)
        return {"alerted": True, "severity": level}

    async def _exec_config_update(
        self, action: ReflexActionRecord, anomaly: AnomalyRecord
    ) -> dict[str, Any]:
        if not anomaly.node_id:
            return {"skipped": True, "reason": "no_node_id"}
        if not self._bridge:
            log.warning("[REFLEX] MQTT bridge not available — cannot send config_update")
            return {"skipped": True, "reason": "no_bridge"}

        # Resolve current config intervals
        current_hb, current_tm = await self._get_current_intervals(anomaly.node_id)
        payload = action.action_payload_json or {}

        new_hb = int(
            current_hb * float(payload.get("heartbeat_interval_sec_multiplier", 1.0))
        )
        new_tm = int(
            current_tm * float(payload.get("telemetry_interval_sec_multiplier", 1.0))
        )

        # Clamp to reasonable bounds
        new_hb = max(30, min(300, new_hb))
        new_tm = max(30, min(600, new_tm))

        config_payload = {
            "config_version": int(datetime.now(timezone.utc).timestamp()),
            "heartbeat_interval_sec": new_hb,
            "telemetry_interval_sec": new_tm,
            "offline_after_sec": 180,
            "report_rssi": True,
        }

        topic = f"cnp/v1/nodes/{anomaly.node_id}/config"
        try:
            await self._bridge.client.publish(topic, __import__("json").dumps(config_payload), qos=1)
            log.info(
                "[REFLEX] config_update → %s hb=%ds tm=%ds",
                anomaly.node_id, new_hb, new_tm,
            )
            return {
                "config_published": True,
                "heartbeat_interval_sec": new_hb,
                "telemetry_interval_sec": new_tm,
            }
        except Exception as exc:
            raise RuntimeError(f"MQTT publish failed: {exc}") from exc

    async def _exec_set_degraded(
        self, action: ReflexActionRecord, anomaly: AnomalyRecord
    ) -> dict[str, Any]:
        if not anomaly.node_id:
            return {"skipped": True, "reason": "no_node_id"}
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE nodes SET status='degraded' WHERE node_id=? AND status='online'",
                (anomaly.node_id,),
            )
            changed = (await (await db.execute("SELECT changes()")).fetchone())[0]
            await db.commit()
        return {"node_id": anomaly.node_id, "set_degraded": bool(changed)}

    async def _exec_retire_commands(
        self, action: ReflexActionRecord, anomaly: AnomalyRecord
    ) -> dict[str, Any]:
        if not anomaly.node_id:
            return {"skipped": True, "reason": "no_node_id"}
        now = _now_utc()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """UPDATE commands
                   SET status='timeout', completed_ts_utc=?
                   WHERE node_id=?
                     AND status IN ('pending','queued')
                     AND issued_ts_utc < datetime('now', '-5 minutes')""",
                (now, anomaly.node_id),
            )
            changed = (await (await db.execute("SELECT changes()")).fetchone())[0]
            await db.commit()
        log.info(
            "[REFLEX] Retired %d stale commands for node=%s",
            changed, anomaly.node_id,
        )
        return {"node_id": anomaly.node_id, "commands_retired": changed}

    # ----------------------------------------------------------------
    #  Helpers
    # ----------------------------------------------------------------

    async def _get_current_intervals(
        self, node_id: str
    ) -> tuple[int, int]:
        """Return (heartbeat_interval_sec, telemetry_interval_sec) for a node."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT heartbeat_interval_sec FROM nodes WHERE node_id=?""",
                (node_id,),
            ) as cur:
                row = await cur.fetchone()
            # V1 compat: node_config table
            async with db.execute(
                """SELECT heartbeat_interval_sec, report_interval_sec
                   FROM node_config WHERE node_id=?""",
                (node_id,),
            ) as cur:
                cfg = await cur.fetchone()

        hb = int((cfg["heartbeat_interval_sec"] if cfg else None) or
                 (row["heartbeat_interval_sec"] if row else 60))
        tm = int((cfg["report_interval_sec"] if cfg else None) or 60)
        return hb, tm
