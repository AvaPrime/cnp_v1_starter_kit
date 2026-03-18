from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from typing import Any

from asyncio_mqtt import Client, MqttError

from .config import settings
from .db import db_connect
from .registry import update_heartbeat, upsert_node
from .storage import (
    insert_ack,
    insert_error,
    insert_event,
    upsert_command_result,
)

log = logging.getLogger("cnp.mqtt")

_MQTT_PER_CLIENT_MAX_PER_SEC = 10
_MQTT_BURST_MAX_PER_5S = 50
_MQTT_INVALID_THRESHOLD = 3
_MQTT_QUARANTINE_SEC = 300
_MQTT_BREACH_WINDOW_SEC = 60
_MQTT_BURST_WINDOW_SEC = 5


class _ClientRateState:
    def __init__(self) -> None:
        self.message_timestamps: deque[float] = deque()
        self.invalid_timestamps: deque[float] = deque()
        self.quarantined_until: float = 0.0

    def is_quarantined(self) -> bool:
        return time.monotonic() < self.quarantined_until

    def quarantine(self, duration_sec: float) -> None:
        self.quarantined_until = time.monotonic() + duration_sec

    def record_message(self, now: float) -> None:
        self.message_timestamps.append(now)

    def record_invalid(self, now: float) -> None:
        self.invalid_timestamps.append(now)

    def _trim(self, dq: deque[float], window: float, now: float) -> None:
        cutoff = now - window
        while dq and dq[0] < cutoff:
            dq.popleft()

    def count_recent(self, window: float, now: float) -> int:
        self._trim(self.message_timestamps, window, now)
        return len(self.message_timestamps)

    def count_invalid(self, now: float) -> int:
        self._trim(self.invalid_timestamps, _MQTT_BREACH_WINDOW_SEC, now)
        return len(self.invalid_timestamps)


ClientFactory = Callable[[], AbstractAsyncContextManager[Client]]


class GatewayMqttBridge:
    def __init__(
        self,
        db_path: str,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.db_path = db_path
        self._client_factory = client_factory or self._default_factory
        self.client: Client | None = None
        self._task: asyncio.Task | None = None
        self._rate_states: dict[str, _ClientRateState] = defaultdict(_ClientRateState)
        self._ops_detector: Any = None

    def set_ops_detector(self, detector: Any) -> None:
        self._ops_detector = detector

    def _default_factory(self) -> AbstractAsyncContextManager[Client]:
        return Client(
            hostname=settings.mqtt_broker_host,
            port=settings.mqtt_broker_port,
            username=settings.mqtt_username or None,
            password=settings.mqtt_password or None,
        )

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="mqtt-bridge")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass

    async def publish_command(
        self, node_id: str, payload: dict[str, Any]
    ) -> None:
        if not self.client:
            raise RuntimeError("MQTT bridge not started")
        topic = f"cnp/v1/nodes/{node_id}/cmd/in"
        envelope = {
            "protocol_version": "CNPv1",
            "message_type": "command",
            "message_id": payload["command_id"],
            "node_id": node_id,
            "ts_utc": _now_utc(),
            "qos": 1,
            "payload": payload,
        }
        await self.client.publish(topic, json.dumps(envelope), qos=1)

    async def _run(self) -> None:
        while True:
            try:
                async with self._client_factory() as client:
                    self.client = client
                    subscription = "cnp/v1/nodes/+/#"
                    async with client.filtered_messages(subscription) as messages:
                        await client.subscribe(subscription, qos=1)
                        log.info("MQTT bridge subscribed to %s", subscription)
                        async for message in messages:
                            topic = str(message.topic)
                            client_id = _extract_node_id(topic)
                            try:
                                raw = message.payload.decode("utf-8")
                            except Exception:
                                self._record_invalid(client_id, topic, "decode_error")
                                continue
                            await self._ingest(topic, raw, client_id)
            except asyncio.CancelledError:
                log.info("MQTT bridge cancelled")
                raise
            except MqttError as exc:
                log.warning("MQTT connection lost: %s — reconnecting in 2s", exc)
                self.client = None
                await asyncio.sleep(2)
            except Exception as exc:
                log.exception("Unexpected bridge error: %s — reconnecting in 5s", exc)
                self.client = None
                await asyncio.sleep(5)

    def _check_rate_limit(self, client_id: str, topic: str) -> bool:
        state = self._rate_states[client_id]
        now = time.monotonic()
        if state.is_quarantined():
            log.warning(
                "[RATE] client_id=%s quarantined — dropping topic=%s",
                client_id, topic,
            )
            return True
        state.record_message(now)
        recent_1s = state.count_recent(1.0, now)
        if recent_1s > _MQTT_PER_CLIENT_MAX_PER_SEC:
            log.warning(
                "[RATE] rate_limit.mqtt.client_breach client_id=%s "
                "msgs_per_sec=%d threshold=%d topic=%s",
                client_id, recent_1s, _MQTT_PER_CLIENT_MAX_PER_SEC, topic,
            )
            return True
        recent_5s = state.count_recent(_MQTT_BURST_WINDOW_SEC, now)
        if recent_5s > _MQTT_BURST_MAX_PER_5S:
            log.warning(
                "[RATE] rate_limit.mqtt.burst_breach client_id=%s "
                "msgs_per_5s=%d threshold=%d topic=%s",
                client_id, recent_5s, _MQTT_BURST_MAX_PER_5S, topic,
            )
            return True
        return False

    def _record_invalid(self, client_id: str, topic: str, reason: str) -> None:
        state = self._rate_states[client_id]
        now = time.monotonic()
        state.record_invalid(now)
        invalid_count = state.count_invalid(now)
        log.warning(
            "[RATE] rate_limit.mqtt.invalid client_id=%s topic=%s "
            "reason=%s count_in_window=%d",
            client_id, topic, reason, invalid_count,
        )
        if invalid_count >= _MQTT_INVALID_THRESHOLD:
            state.quarantine(_MQTT_QUARANTINE_SEC)
            log.error(
                "[RATE] rate_limit.mqtt.invalid_breach client_id=%s "
                "QUARANTINED for %ds",
                client_id, _MQTT_QUARANTINE_SEC,
            )

    async def _ingest(
        self, topic: str, payload_text: str, client_id: str
    ) -> None:
        if self._check_rate_limit(client_id, topic):
            return
        try:
            envelope = json.loads(payload_text)
        except json.JSONDecodeError:
            self._record_invalid(client_id, topic, "json_parse_error")
            return
        msg_type = envelope.get("message_type", "")
        suffix = _topic_suffix(topic)
        dispatch: dict[str, Any] = {
            "hello": self._handle_hello,
            "heartbeat": self._handle_heartbeat,
            "events": self._handle_event,
            "errors": self._handle_error,
            "ack": self._handle_ack,
            "cmd/out": self._handle_command_result,
            "cmd/in": None,
            "config": None,
            "state": self._handle_state,
        }
        handler = dispatch.get(suffix)
        if handler is None:
            log.debug("No handler for topic suffix=%s — ignoring", suffix)
            return
        try:
            await handler(envelope)
        except Exception as exc:
            log.exception(
                "Handler error for topic=%s msg_type=%s: %s",
                topic, msg_type, exc,
            )

    async def _handle_hello(self, envelope: dict[str, Any]) -> None:
        await upsert_node(self.db_path, envelope)
        node_id = envelope.get("node_id", "")
        if self.client:
            ack_topic = f"cnp/v1/nodes/{node_id}/ack"
            ack = {
                "protocol_version": "CNPv1",
                "message_type": "register_ack",
                "message_id": f"ack-{envelope.get('message_id', 'unknown')}",
                "node_id": node_id,
                "ts_utc": _now_utc(),
                "qos": 1,
                "payload": {
                    "accepted": True,
                    "gateway_id": settings.gateway_id,
                    "assigned_config_version": 1,
                    "heartbeat_interval_sec": 60,
                    "event_batch_max": 16,
                    "offline_after_sec": settings.offline_after_seconds,
                },
            }
            await self.client.publish(ack_topic, json.dumps(ack), qos=1)

    async def _handle_heartbeat(self, envelope: dict[str, Any]) -> None:
        await update_heartbeat(self.db_path, envelope)
        if self._ops_detector:
            await self._ops_detector.on_heartbeat(envelope)

    async def _handle_event(self, envelope: dict[str, Any]) -> None:
        await insert_event(self.db_path, envelope)

    async def _handle_error(self, envelope: dict[str, Any]) -> None:
        await insert_error(self.db_path, envelope)

    async def _handle_ack(self, envelope: dict[str, Any]) -> None:
        await insert_ack(self.db_path, envelope)

    async def _handle_command_result(self, envelope: dict[str, Any]) -> None:
        await upsert_command_result(self.db_path, envelope)

    async def _handle_state(self, envelope: dict[str, Any]) -> None:
        node_id = envelope.get("node_id")
        if node_id:
            async with db_connect(self.db_path) as db:
                await db.execute(
                    "UPDATE nodes SET last_seen_utc=?, status=? WHERE node_id=?",
                    (
                        _now_utc(),
                        envelope.get("payload", {}).get("status", "online"),
                        node_id,
                    ),
                )
                await db.commit()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_node_id(topic: str) -> str:
    parts = topic.split("/")
    return parts[3] if len(parts) >= 4 else "unknown"


def _topic_suffix(topic: str) -> str:
    parts = topic.split("/", 4)
    return parts[4] if len(parts) >= 5 else ""


class MockMqttBridge:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.client = asyncio.Future()
        self._ops_detector: Any = None

    def set_ops_detector(self, detector: Any) -> None:
        self._ops_detector = detector

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def publish_command(self, node_id: str, payload: dict[str, Any]) -> None:
        topic = f"cnp/v1/nodes/{node_id}/cmd/in"
        self.published.append((topic, json.dumps(payload)))
