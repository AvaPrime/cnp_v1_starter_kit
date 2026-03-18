"""
gateway/app/core/config.py
──────────────────────────
Centralised settings loaded from environment variables.

Audit additions:
  - ADMIN_TOKEN       : required for admin endpoint access (P0-05)
  - TRUSTED_PROXIES   : comma-separated CIDRs/IPs of trusted reverse proxies (P1-04)
  - DB_QUERY_TIMEOUT  : per-query asyncio timeout in seconds (P3-08)
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # ── MQTT ────────────────────────────────────────────────────
    mqtt_broker_host: str = os.getenv("MQTT_BROKER_HOST", "127.0.0.1")
    mqtt_broker_port: int = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    mqtt_username: str = os.getenv("MQTT_USERNAME", "")
    mqtt_password: str = os.getenv("MQTT_PASSWORD", "")

    # ── Database ────────────────────────────────────────────────
    gateway_db_path: str = os.getenv("GATEWAY_DB_PATH", "./cnp_gateway.db")
    db_query_timeout_sec: float = float(os.getenv("DB_QUERY_TIMEOUT_SEC", "3.0"))

    # ── Gateway identity ────────────────────────────────────────
    gateway_id: str = os.getenv("CNP_GATEWAY_ID", "codessa-gateway-local")
    offline_after_seconds: int = int(os.getenv("CNP_OFFLINE_AFTER_SECONDS", "180"))

    # ── Auth (P0-05) ────────────────────────────────────────────
    # ADMIN_TOKEN is read directly in admin.py to avoid circular imports,
    # but duplicated here so it appears in settings introspection / docs.
    admin_token_configured: bool = bool(os.getenv("ADMIN_TOKEN", ""))

    # ── Network security (P1-04) ────────────────────────────────
    # Comma-separated list of trusted reverse-proxy IPs or CIDRs.
    # If set, X-Forwarded-For is only trusted when the direct client IP
    # is in this list. Empty string = trust no proxy (use direct client IP).
    trusted_proxies_raw: str = os.getenv("TRUSTED_PROXIES", "")

    @property
    def trusted_proxies(self) -> frozenset[str]:
        if not self.trusted_proxies_raw:
            return frozenset()
        return frozenset(
            p.strip()
            for p in self.trusted_proxies_raw.split(",")
            if p.strip()
        )


settings = Settings()
