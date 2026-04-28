"""GitHub OAuth 2.0 authorization code exchange with PKCE (RFC 7636)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any
from urllib.parse import urlencode

import requests
from django.conf import settings

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return verifier, challenge


def build_authorize_url(
    *,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scope: str = "read:user user:email",
) -> str:
    q = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": scope,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(q)}"


def exchange_code_for_token(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """POST to GitHub; returns JSON including access_token (GitHub) or raises on error."""
    headers = {
        "Accept": "application/json",
    }
    data: dict[str, str] = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    secret = getattr(settings, "GITHUB_CLIENT_SECRET", "").strip()
    if secret:
        data["client_secret"] = secret

    r = requests.post(GITHUB_TOKEN_URL, data=data, headers=headers, timeout=30)
    try:
        body = r.json()
    except json.JSONDecodeError as e:
        raise ValueError("Invalid GitHub token response") from e
    if r.status_code != 200:
        msg = body.get("error_description") or body.get("error") or r.text
        raise ValueError(msg)
    if "access_token" not in body:
        raise ValueError(body.get("error_description") or "Missing access_token")
    return body


def fetch_github_user(github_access_token: str) -> dict[str, Any]:
    r = requests.get(
        GITHUB_USER_URL,
        headers={
            "Authorization": f"Bearer {github_access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def upsert_user_from_github_profile(data: dict[str, Any]) -> Any:
    from django.utils import timezone

    from accounts.models import User, UserRole

    github_id = str(data["id"])
    username = str(data.get("login") or "")
    email = str(data.get("email") or "")[:255]
    avatar = str(data.get("avatar_url") or "")[:500]

    user, _created = User.objects.get_or_create(
        github_id=github_id,
        defaults={
            "username": username or f"gh_{github_id}",
            "email": email,
            "avatar_url": avatar,
            "role": UserRole.ANALYST,
        },
    )
    user.username = username or user.username
    user.email = email or user.email
    user.avatar_url = avatar or user.avatar_url
    user.last_login_at = timezone.now()
    user.save(update_fields=["username", "email", "avatar_url", "last_login_at"])
    return user
