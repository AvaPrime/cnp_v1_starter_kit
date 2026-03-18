"""
gateway/app/core/rate_limit.py
──────────────────────────────
HTTP and MQTT rate limiting for the CNP Gateway.

Audit fixes:
  P1-04 — X-Forwarded-For is now only trusted if the direct client IP is in
           TRUSTED_PROXIES. Spoofed headers from untrusted sources are ignored.

  NOTE (P3-04): Rate limiter state is still process-local (in-memory).
  For multi-worker deployments this means each worker maintains independent
  windows — effective rate budget = configured_max × worker_count.
  Phase 3 will replace this with a Redis-backed shared counter.
"""
from __future__ import annotations

import ipaddress
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

log = logging.getLogger("cnp.rate_limit")

_NODE_MAX = 60
_NODE_WINDOW_SEC = 60
_IP_MAX = 200
_IP_WINDOW_SEC = 60
_GLOBAL_MAX = 2000
_GLOBAL_WINDOW_SEC = 60
_BOOTSTRAP_MAX = 30
_BOOTSTRAP_WINDOW_SEC = 60


class _SlidingWindow:
    def __init__(self, max_count: int, window_sec: float) -> None:
        self.max_count = max_count
        self.window_sec = window_sec
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        bucket = self._buckets[key]
        cutoff = now - self.window_sec
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        count = len(bucket)
        if count >= self.max_count:
            return False, count + 1
        bucket.append(now)
        return True, count + 1

    def retry_after(self, key: str) -> int:
        bucket = self._buckets.get(key)
        if not bucket:
            return 1
        now = time.monotonic()
        return max(1, int(self.window_sec - (now - bucket[0])) + 1)


_node_limiter = _SlidingWindow(_NODE_MAX, _NODE_WINDOW_SEC)
_ip_limiter = _SlidingWindow(_IP_MAX, _IP_WINDOW_SEC)
_global_limiter = _SlidingWindow(_GLOBAL_MAX, _GLOBAL_WINDOW_SEC)
_bootstrap_limiter = _SlidingWindow(_BOOTSTRAP_MAX, _BOOTSTRAP_WINDOW_SEC)


def _extract_node_id_from_path(path: str) -> str | None:
    """Extract node_id from /api/node/commands/{node_id} style paths."""
    parts = path.strip("/").split("/")
    if len(parts) >= 4 and parts[2] == "commands":
        return parts[3]
    return None


def _is_trusted_proxy(ip: str) -> bool:
    """Check if a direct client IP is in the TRUSTED_PROXIES set."""
    from .config import settings
    if not settings.trusted_proxies:
        return False
    try:
        client_addr = ipaddress.ip_address(ip)
        for proxy in settings.trusted_proxies:
            try:
                if "/" in proxy:
                    if client_addr in ipaddress.ip_network(proxy, strict=False):
                        return True
                else:
                    if client_addr == ipaddress.ip_address(proxy):
                        return True
            except ValueError:
                continue
    except ValueError:
        pass
    return False


def _client_ip(request: Request) -> str:
    """
    Extract the real client IP.

    P1-04: X-Forwarded-For is only trusted when the direct client IP
    is in TRUSTED_PROXIES. Without this guard, any client can spoof
    their IP to bypass per-IP rate limits.
    """
    direct_ip = request.client.host if request.client else "unknown"

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded and _is_trusted_proxy(direct_ip):
        # Take the leftmost (originating) IP from the chain
        return forwarded.split(",")[0].strip()

    return direct_ip


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if not (path.startswith("/api/node/") or path.startswith("/v1/compat/node/")):
            return await call_next(request)

        ip = _client_ip(request)
        node_id = _extract_node_id_from_path(path)

        global_ok, global_count = _global_limiter.is_allowed("__global__")
        if not global_ok:
            log.error(
                "rate_limit.global_breach source_ip=%s path=%s count=%d",
                ip, path, global_count,
            )
            return _too_many(
                "Global rate limit exceeded",
                _global_limiter.retry_after("__global__"),
            )

        ip_ok, ip_count = _ip_limiter.is_allowed(ip)
        if not ip_ok:
            log.warning(
                "rate_limit.ip_breach source_ip=%s path=%s count=%d",
                ip, path, ip_count,
            )
            return _too_many(
                "Source IP rate limit exceeded",
                _ip_limiter.retry_after(ip),
            )

        if node_id:
            node_ok, node_count = _node_limiter.is_allowed(node_id)
            if not node_ok:
                log.warning(
                    "rate_limit.node_breach node_id=%s source_ip=%s count=%d",
                    node_id, ip, node_count,
                )
                return _too_many(
                    "Node rate limit exceeded",
                    _node_limiter.retry_after(node_id),
                )

        if path.endswith("/hello") or path.endswith("/node/hello"):
            boot_ok, boot_count = _bootstrap_limiter.is_allowed("bootstrap")
            if not boot_ok:
                log.warning(
                    "rate_limit.bootstrap_breach source_ip=%s count=%d", ip, boot_count
                )
                return _too_many(
                    "Registration rate limit exceeded",
                    _bootstrap_limiter.retry_after("bootstrap"),
                )

        return await call_next(request)


def _too_many(detail: str, retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "too_many_requests", "detail": detail},
        headers={"Retry-After": str(retry_after)},
    )


def check_node_rate(node_id: str) -> tuple[bool, int]:
    """
    Called from route handlers for body-level node_id rate check.

    NOTE: This fires AFTER the middleware has already checked. The double-dip
    is intentional only for /node/hello where we want to inspect the body's
    node_id (which differs from the URL path node_id). For all other routes,
    rely on the middleware check alone (P1-05 will remove the redundant calls).
    """
    ok, count = _node_limiter.is_allowed(node_id)
    if not ok:
        log.warning(
            "rate_limit.node_breach node_id=%s count=%d (body-level check)",
            node_id, count,
        )
        return False, _node_limiter.retry_after(node_id)
    return True, 0
