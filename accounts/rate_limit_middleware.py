"""IP buckets for `/auth/*` plus structured request logging.

`/api/*` deliberately skips here because DRF throttles run after JWT resolves the user.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Callable

from django.http import HttpRequest, HttpResponse, JsonResponse

logger = logging.getLogger(__name__)

_rate_limit_store: dict[str, list[float]] = defaultdict(
    list
)  # RAM-only; resets per process — pair with Redis for multi-node hard limits


def _is_drf_auth_burst_path(p: str) -> bool:
    """Whether this URL already has matching AuthBurstThrottle limits inside DRF."""
    if p == "/auth/me" or p.startswith("/auth/me/"):
        return True
    if p == "/auth/github/cli" or p.startswith("/auth/github/cli/"):
        return True
    if p.startswith("/auth/refresh/web"):
        return False
    if p == "/auth/refresh" or p.startswith("/auth/refresh/"):
        return True
    if p.startswith("/auth/logout/web"):
        return False
    if p == "/auth/logout" or p.startswith("/auth/logout/"):
        return True
    return False


def _get_rate_limit_key(request: HttpRequest, p: str) -> tuple[str, int, int]:
    """Return `(redis_key, max_hits, window_secs)`; empty key means this middleware skips."""
    # Match TRD: authenticated /api traffic is throttled per user inside DRF, not by IP here.
    if p == "/api" or p.startswith("/api/"):
        return "", 0, 0
    # Browser OAuth redirects can spike; GitHub/browser handle abuse — do not 429 locally.
    if p in (
        "/auth/github/callback",
    ):
        return "", 0, 0
    # Remaining /auth/* JSON endpoints share the same burst policy as DRF throttles.
    if _is_drf_auth_burst_path(p):
        return "", 0, 0
    if p.startswith("/auth"):
        ip = request.META.get("REMOTE_ADDR", "unknown")
        return f"auth:{ip}", 10, 60
    return "", 0, 0


def _check_rate_limit(key: str, limit: int, window: int) -> bool:
    """Sliding-window counter: True if request should proceed, False if budget exhausted."""
    now = time.time()
    cutoff = now - window
    _rate_limit_store[key] = [ts for ts in _rate_limit_store[key] if ts > cutoff]
    if len(_rate_limit_store[key]) >= limit:
        return False
    _rate_limit_store[key].append(now)
    return True


class RateLimitMiddleware:
    """Return 429 JSON when anonymous `/auth/*` traffic exceeds configured windows."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        p = request.path.rstrip("/") or "/"
        key, limit, window = _get_rate_limit_key(request, p)
        if key and not _check_rate_limit(key, limit, window):
            return JsonResponse(
                {"status": "error", "message": "Too many requests"},
                status=429,
            )
        return self.get_response(request)


class RequestLoggingMiddleware:
    """Emit concise structured INFO lines (`method/path/status/duration/user_id`)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        start = time.time()
        response = self.get_response(request)
        duration_ms = int((time.time() - start) * 1000)

        user = getattr(request, "user", None)
        user_id = None
        if user and getattr(user, "is_authenticated", False):
            user_id = str(getattr(user, "pk", None))

        logger.info(
            "method=%s path=%s status=%s duration_ms=%d user_id=%s",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            user_id or "anonymous",
        )
        return response
