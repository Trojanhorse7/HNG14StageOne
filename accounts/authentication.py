"""JWT access via Authorization: Bearer or insighta_access cookie."""

from __future__ import annotations

import uuid

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated

from accounts.models import User
from accounts.tokens import decode_access_token


class JWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = None
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if header.startswith("Bearer "):
            token = header[7:].strip()
        if not token:
            token = request.COOKIES.get("insighta_access")
        if not token:
            # Force 401 instead of letting DRF return 403 when no credentials provided
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
        """Return WWW-Authenticate header value for 401 responses (DRF requirement)."""
        return 'Bearer realm="api"'
