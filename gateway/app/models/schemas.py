from __future__ import annotations
import json
import logging
import os
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

log = logging.getLogger("cnp.models")

# Bootstrap token for Stage 1 auth
BOOTSTRAP_TOKEN: str = os.environ.get("BOOTSTRAP_TOKEN", "")
if not BOOTSTRAP_TOKEN:
    log.warning(
        "BOOTSTRAP_TOKEN env var not set — auth middleware will reject all node requests."
    )


class NodeResponse(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    protocol_version: str
    firmware_version: str
    hardware_model: str
    capabilities_json: str
    config_version: int
    status: str
    last_seen_utc: str | None
    first_seen_utc: str
    boot_reason: str | None
    heartbeat_interval_sec: int
    offline_after_sec: int
    last_rssi: int | None
    battery_pct: float | None
    free_heap_bytes: int | None
    queue_depth: int
    supports_ota: int
    ota_channel: str | None = None
    ota_last_result: str | None = None
    tags_json: str = "[]"
    zone: str | None = None
    device_uid: str | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "NodeResponse":
        allowed = cls.model_fields.keys()
        return cls(**{k: row[k] for k in allowed if k in row})


class MessageType(str, Enum):
    hello = "hello"
    register_ack = "register_ack"
    heartbeat = "heartbeat"
    state_update = "state_update"
    event = "event"
    ack = "ack"
    command = "command"
    command_result = "command_result"
    error = "error"
    config_update = "config_update"


_NODE_ID_PATTERN = re.compile(r"^[a-z0-9-]{3,64}$")


class Envelope(BaseModel):
    protocol_version: Literal["CNPv1"]
    message_type: MessageType
    message_id: str = Field(min_length=4, max_length=64)
    node_id: str
    ts_utc: str
    qos: Literal[0, 1] = 0
    correlation_id: str | None = None
    payload: dict[str, Any]
    sig: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalise_v1_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "protocol" in data and "protocol_version" not in data:
            log.warning(
                "DEPRECATION_V1_KEY original_key=protocol canonical_key=protocol_version node_id=%s",
                data.get("node_id", "unknown"),
            )
            data["protocol_version"] = data.pop("protocol")
        if "timestamp" in data and "ts_utc" not in data:
            log.warning(
                "DEPRECATION_V1_KEY original_key=timestamp canonical_key=ts_utc node_id=%s",
                data.get("node_id", "unknown"),
            )
            data["ts_utc"] = data.pop("timestamp")
        if "ts_utc" in data and isinstance(data["ts_utc"], str) and data["ts_utc"].endswith("+00:00"):
            data["ts_utc"] = data["ts_utc"].replace("+00:00", "Z")
        if "message_id" not in data or not data.get("message_id"):
            import uuid
            data["message_id"] = str(uuid.uuid4())
        return data

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, v: str) -> str:
        if not _NODE_ID_PATTERN.match(v):
            raise ValueError("node_id must match ^[a-z0-9-]{3,64}$")
        return v

    @field_validator("ts_utc")
    @classmethod
    def validate_ts_utc(cls, v: str) -> str:
        if not v.endswith("Z"):
            raise ValueError("ts_utc must end with Z")
        return v


class CommandRequest(BaseModel):
    command_type: str
    category: Literal["control", "configuration", "maintenance", "power"]
    timeout_ms: int = Field(ge=100, le=600000)
    arguments: dict[str, Any] = Field(default_factory=dict)
    issued_by: str = "gateway"
    dry_run: bool = False


def validate_bootstrap_token(token: str | None) -> bool:
    if not BOOTSTRAP_TOKEN:
        return False
    if not token:
        return False
    import hmac
    return hmac.compare_digest(token.strip(), BOOTSTRAP_TOKEN.strip())
