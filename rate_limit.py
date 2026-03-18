"""
CNP EPIC-01 — P1-04
HTTP rate limiting middleware.

Three rolling-window tiers:
  Per node_id:   60 req / 60s  → 429 + Retry-After
  Per source IP: 200 req / 60s → 429 + Retry-After
  Global:        2000 req / 60s → 429 + alert log

Every breach emits a structured log event with:
  event_type, node_id (if present), source_ip, window, count

State is in-process (no Redis). Clears on gateway restart
(acceptable for Phase 1 per CNP-BOARD-003 P1-04 spec).

Bootstrap token registration is additionally rate-limited
to 30 registrations/minute to prevent enumeration.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

log = logging.getLogger("cnp.rate_limit")

# ----------------------------------------------------------------
#  Limits
# ----------------------------------------------------------------
_NODE_MAX            = 60
_NODE_WINDOW_SEC     = 60
_IP_MAX              = 200
_IP_WINDOW_SEC       = 60
_GLOBAL_MAX          = 2000
_GLOBAL_WINDOW_SEC   = 60
_BOOTSTRAP_MAX       = 30
_BOOTSTRAP_WINDOW_SEC = 60


class _SlidingWindow:
    """Thread-safe (asyncio single-threaded) sliding window counter."""

    def __init__(self, max_count: int, window_sec: float) -> None:
        self.max_count  = max_count
        self.window_sec = window_sec
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """
        Returns (allowed, current_count).
        Records the request if allowed.
        """
        now = time.monotonic()
        bucket = self._buckets[key]

        # Trim expired entries
        cutoff = now - self.window_sec
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        count = len(bucket)
        if count >= self.max_count:
            return False, count + 1

        bucket.append(now)
        return True, count + 1

    def retry_after(self, key: str) -> int:
        """Seconds until the oldest entry in the window expires."""
        bucket = self._buckets.get(key)
        if not bucket:
            return 1
        now = time.monotonic()
        return max(1, int(self.window_sec - (now - bucket[0])) + 1)


# Module-level rate limit instances
_node_limiter      = _SlidingWindow(_NODE_MAX,      _NODE_WINDOW_SEC)
_ip_limiter        = _SlidingWindow(_IP_MAX,        _IP_WINDOW_SEC)
_global_limiter    = _SlidingWindow("__global__", _GLOBAL_WINDOW_SEC)  # type: ignore[arg-type]
_bootstrap_limiter = _SlidingWindow(_BOOTSTRAP_MAX, _BOOTSTRAP_WINDOW_SEC)

# Patch: global limiter uses a single key
_global_limiter = _SlidingWindow(_GLOBAL_MAX, _GLOBAL_WINDOW_SEC)


def _extract_node_id_from_request(request: Request) -> str | None:
    """
    Best-effort node_id extraction from the URL path.
    /api/node/commands/cnp-xxx → cnp-xxx
    /api/node/hello → None (not in path, checked from body in handler)
    """
    path = request.url.path
    parts = path.strip("/").split("/")
    # /api/node/commands/{node_id}
    if len(parts) >= 4 and parts[2] == "commands":
        return parts[3]
    return None


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Applied to all /api/node/* routes.
    Also monitors bootstrap registrations via /api/node/hello.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Only apply to node-inbound routes
        if not (path.startswith("/api/node/") or path.startswith("/v1/compat/node/")):
            return await call_next(request)

        ip = _client_ip(request)
        node_id = _extract_node_id_from_request(request)

        # 1. Global limit
        global_ok, global_count = _global_limiter.is_allowed("__global__")
        if not global_ok:
            log.error(
                "rate_limit.http.global_breach source_ip=%s path=%s count=%d",
                ip, path, global_count,
            )
            return _too_many(
                "Global rate limit exceeded",
                _global_limiter.retry_after("__global__"),
            )

        # 2. Per-IP limit
        ip_ok, ip_count = _ip_limiter.is_allowed(ip)
        if not ip_ok:
            log.warning(
                "rate_limit.http.ip_breach source_ip=%s path=%s count=%d",
                ip, path, ip_count,
            )
            return _too_many(
                "Source IP rate limit exceeded",
                _ip_limiter.retry_after(ip),
            )

        # 3. Per-node limit (URL path only — body not parsed here)
        if node_id:
            node_ok, node_count = _node_limiter.is_allowed(node_id)
            if not node_ok:
                log.warning(
                    "rate_limit.http.node_breach node_id=%s source_ip=%s count=%d",
                    node_id, ip, node_count,
                )
                return _too_many(
                    "Node rate limit exceeded",
                    _node_limiter.retry_after(node_id),
                )

        # 4. Bootstrap registration limit on /hello
        if path.endswith("/hello") or path.endswith("/node/hello"):
            boot_ok, boot_count = _bootstrap_limiter.is_allowed("bootstrap")
            if not boot_ok:
                log.warning(
                    "rate_limit.http.bootstrap_breach source_ip=%s count=%d",
                    ip, boot_count,
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


# ----------------------------------------------------------------
#  Public helper — check node_id rate from handler body
#  (called after body parse when node_id is in the JSON payload)
# ----------------------------------------------------------------

def check_node_rate(node_id: str) -> tuple[bool, int]:
    """
    Check per-node rate limit from within a route handler,
    after the node_id has been extracted from the request body.
    Returns (allowed, retry_after_sec).
    """
    ok, count = _node_limiter.is_allowed(node_id)
    if not ok:
        log.warning(
            "rate_limit.http.node_breach node_id=%s count=%d (body check)",
            node_id, count,
        )
        return False, _node_limiter.retry_after(node_id)
    return True, 0
