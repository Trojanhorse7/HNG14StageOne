"""DRF throttles layered on Django cache (DatabaseCache on Postgres, LocMem on SQLite)."""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


class ApiUserThrottle(SimpleRateThrottle):
    """Burst-y API guard: prefer authenticated user id, else fall back to anonymous IP."""

    scope = "api_user"

    def get_cache_key(self, request, view) -> str | None:
        """Prefer authenticated user id; anonymous clients fall back to client IP."""
        if request.user and getattr(request.user, "is_authenticated", False):
            ident = str(request.user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class AuthBurstThrottle(SimpleRateThrottle):
    """Shared 10/min IP bucket for auth endpoints also enforced via middleware elsewhere."""

    scope = "auth_burst"

    def get_cache_key(self, request, view) -> str | None:
        """Always throttle burst auth traffic by client IP (matches middleware policy)."""
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
