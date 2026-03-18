from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from asyncio_mqtt import Client, MqttError

from .config import settings
from .registry import upsert_node, update_heartbeat
from .storage import insert_ack, insert_error, insert_event, upsert_command_result

log = logging.getLogger(__name__)


class GatewayMqttBridge:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.client: Client | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self.client:
            await self.client.disconnect()

    async def publish_command(self, node_id: str, payload: dict[str, Any]) -> None:
        if not self.client:
            raise RuntimeError("MQTT bridge not started")
        topic = f"cnp/v1/nodes/{node_id}/cmd/in"
        envelope = {
            "protocol_version": "CNPv1",
            "message_type": "command",
            "message_id": payload["command_id"],
            "node_id": node_id,
            "ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "qos": 1,
            "payload": payload,
        }
        await self.client.publish(topic, json.dumps(envelope), qos=1)

    async def _run(self) -> None:
        while True:
            try:
                async with Client(
                    hostname=settings.mqtt_broker_host,
                    port=settings.mqtt_broker_port,
                    username=settings.mqtt_username or None,
                    password=settings.mqtt_password or None,
                ) as client:
                    self.client = client
                    async with client.filtered_messages("cnp/v1/nodes/+/#") as messages:
                        await client.subscribe("cnp/v1/nodes/+/#")
                        async for message in messages:
                            await self._handle(str(message.topic), message.payload.decode())
            except asyncio.CancelledError:
                raise
            except MqttError as exc:  # pragma: no cover - only used with real broker
                log.warning("MQTT bridge disconnected: %s", exc)
                await asyncio.sleep(2)

    async def _handle(self, topic: str, payload_text: str) -> None:
        envelope = json.loads(payload_text)
        msg_type = envelope["message_type"]

        if msg_type == "hello":
            await upsert_node(self.db_path, envelope)
            if self.client:
                node_id = envelope["node_id"]
                ack_topic = f"cnp/v1/nodes/{node_id}/ack"
                ack = {
                    "protocol_version": "CNPv1",
                    "message_type": "register_ack",
                    "message_id": f"ack-{envelope['message_id']}",
                    "node_id": node_id,
                    "ts_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
        elif msg_type == "heartbeat":
            await update_heartbeat(self.db_path, envelope)
        elif msg_type == "event":
            await insert_event(self.db_path, envelope)
        elif msg_type == "error":
            await insert_error(self.db_path, envelope)
        elif msg_type == "ack":
            await insert_ack(self.db_path, envelope)
        elif msg_type == "command_result":
            await upsert_command_result(self.db_path, envelope)
