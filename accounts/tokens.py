"""JWT access tokens and opaque refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

import jwt
from django.conf import settings
from django.utils import timezone

from accounts.models import RefreshToken, User


def _jwt_key() -> str:
    return getattr(settings, "JWT_SIGNING_KEY", None) or settings.SECRET_KEY


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_refresh_token_string() -> str:
    return secrets.token_urlsafe(48)


def create_access_token(user: User) -> str:
    now = timezone.now()
    exp = now + timedelta(seconds=settings.ACCESS_TOKEN_LIFETIME_SECONDS)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "role": user.role,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, _jwt_key(), algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, _jwt_key(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def issue_refresh_token_row(user: User) -> tuple[RefreshToken, str]:
    raw = generate_refresh_token_string()
    expires = timezone.now() + timedelta(seconds=settings.REFRESH_TOKEN_LIFETIME_SECONDS)
    row = RefreshToken.objects.create(
        user=user,
        token_hash=hash_refresh_token(raw),
        expires_at=expires,
    )
    return row, raw


def issue_token_pair(user: User) -> tuple[str, str]:
    access = create_access_token(user)
    _, refresh_raw = issue_refresh_token_row(user)
    return access, refresh_raw
