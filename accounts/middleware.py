"""Require X-API-Version: 1 for all /api/* routes."""

from __future__ import annotations

from typing import Callable

from django.http import HttpRequest, HttpResponse, JsonResponse

API_VERSION_HEADER = "HTTP_X_API_VERSION"
EXPECTED_VERSION = "1"
ERR_MESSAGE = "API version header required"


class ApiVersionMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path
        if path.startswith("/api/") or path.rstrip("/") == "/api":
            raw = request.META.get(API_VERSION_HEADER)
            if raw is None and hasattr(request, "headers"):
                raw = request.headers.get("X-API-Version")
            if str(raw or "").strip() != EXPECTED_VERSION:
                return JsonResponse(
                    {"status": "error", "message": ERR_MESSAGE},
                    status=400,
                )
        return self.get_response(request)
