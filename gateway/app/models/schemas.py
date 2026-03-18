from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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


class Envelope(BaseModel):
    protocol_version: Literal["CNPv1"]
    message_type: MessageType
    message_id: str = Field(min_length=20, max_length=36)
    node_id: str = Field(pattern=r"^[a-z0-9-]{3,64}$")
    ts_utc: datetime
    qos: Literal[0, 1]
    correlation_id: str | None = None
    payload: dict[str, Any]
    sig: str | None = None

    @field_validator("ts_utc", mode="before")
    @classmethod
    def ensure_datetime(cls, v: Any) -> Any:
        return v


class CommandRequest(BaseModel):
    command_type: str
    category: Literal["control", "configuration", "maintenance", "power"]
    timeout_ms: int = Field(ge=100, le=600000)
    arguments: dict[str, Any] = Field(default_factory=dict)
    issued_by: str = "gateway"
    dry_run: bool = False
