from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mqtt_broker_host: str = os.getenv("MQTT_BROKER_HOST", "127.0.0.1")
    mqtt_broker_port: int = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    mqtt_username: str = os.getenv("MQTT_USERNAME", "")
    mqtt_password: str = os.getenv("MQTT_PASSWORD", "")
    gateway_db_path: str = os.getenv("GATEWAY_DB_PATH", "./cnp_gateway.db")
    offline_after_seconds: int = int(os.getenv("CNP_OFFLINE_AFTER_SECONDS", "180"))
    gateway_id: str = os.getenv("CNP_GATEWAY_ID", "codessa-gateway-local")


settings = Settings()
