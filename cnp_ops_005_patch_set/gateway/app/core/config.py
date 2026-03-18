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
    enable_mqtt_bridge: bool = os.getenv("CNP_ENABLE_MQTT_BRIDGE", "true").lower() == "true"
    ops_command_lag_threshold_ms: int = int(os.getenv("CNP_OPS_COMMAND_LAG_THRESHOLD_MS", "5000"))
    ops_queue_depth_threshold: int = int(os.getenv("CNP_OPS_QUEUE_DEPTH_THRESHOLD", "10"))
    ops_rssi_threshold: int = int(os.getenv("CNP_OPS_RSSI_THRESHOLD", "-80"))
    ops_flap_threshold: int = int(os.getenv("CNP_OPS_FLAP_THRESHOLD", "4"))


settings = Settings()
