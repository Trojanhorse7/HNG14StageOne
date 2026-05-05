"""DRF authentication: pull JWT from Bearer header or `insighta_access` cookie.

Missing credentials raise `NotAuthenticated` so anonymous API calls return HTTP 401 per spec.
"""

from __future__ import annotations

import uuid

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated

from accounts.models import User
from accounts.tokens import decode_access_token


class JWTAuthentication(BaseAuthentication):
    """Resolve Django `User` from HS256 access payload (`sub` must match primary key UUID)."""

    def authenticate(self, request):
        """Return `(user, None)` or raise REST auth errors."""
        token = None
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if header.startswith("Bearer "):
            token = header[7:].strip()
        if not token:
            token = request.COOKIES.get("insighta_access")
        if not token:
            # No Authorization/cookie: force 401 so anonymous API calls are not treated as 403.
            raise NotAuthenticated("Authentication credentials were not provided.")

        payload = decode_access_token(token)
        if not payload or payload.get("typ") != "access":
            raise AuthenticationFailed("Invalid or expired token")

        try:
            uid = uuid.UUID(str(payload.get("sub")))
        except (ValueError, TypeError) as e:
            raise AuthenticationFailed("Invalid token subject") from e

        try:
            user = User.objects.get(pk=uid)
        except User.DoesNotExist as e:
            raise AuthenticationFailed("User not found") from e

        return (user, None)

    def authenticate_header(self, request):
        """Expose `WWW-Authenticate: Bearer realm="api"` on 401 responses."""
        return 'Bearer realm="api"'
