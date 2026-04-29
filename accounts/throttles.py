"""DRF throttles: per-user API budget; burst limit for selected auth endpoints."""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


class ApiUserThrottle(SimpleRateThrottle):
    """60/min keyed by authenticated user id, else client IP."""

    scope = "api_user"

    def get_cache_key(self, request, view) -> str | None:
        if request.user and getattr(request.user, "is_authenticated", False):
            ident = str(request.user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class AuthBurstThrottle(SimpleRateThrottle):
    """10/min by IP for DRF login-adjacent endpoints (matches middleware for browser OAuth)."""

    scope = "auth_burst"

    def get_cache_key(self, request, view) -> str | None:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
