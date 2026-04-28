"""Rate limiting and request logging middleware."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

logger = logging.getLogger(__name__)

# In-memory rate limit store (use Redis in production)
_rate_limit_store: dict[str, list[float]] = defaultdict(list)


def _get_rate_limit_key(request: HttpRequest, path: str) -> tuple[str, int, int]:
    """Return (key, limit, window_seconds) based on path and user."""
    if path.startswith("/auth/"):
        ip = request.META.get("REMOTE_ADDR", "unknown")
        return f"auth:{ip}", 10, 60
    elif path.startswith("/api/"):
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            user_id = getattr(user, "pk", "anonymous")
            return f"api:{user_id}", 60, 60
        return f"api:anon:{request.META.get('REMOTE_ADDR', 'unknown')}", 60, 60
    return "", 0, 0


def _check_rate_limit(key: str, limit: int, window: int) -> bool:
    """Return True if under limit, False if exceeded."""
    now = time.time()
    cutoff = now - window
    _rate_limit_store[key] = [ts for ts in _rate_limit_store[key] if ts > cutoff]
    if len(_rate_limit_store[key]) >= limit:
        return False
    _rate_limit_store[key].append(now)
    return True


class RateLimitMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path.rstrip("/")
        key, limit, window = _get_rate_limit_key(request, path)
        if key and not _check_rate_limit(key, limit, window):
            return JsonResponse(
                {"status": "error", "message": "Too many requests"},
                status=429,
            )
        return self.get_response(request)


class RequestLoggingMiddleware:
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
