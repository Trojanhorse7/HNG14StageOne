"""GitHub OAuth authorize URL builder and token exchange (PKCE RFC 7636).

Split credentials: browser portal uses `GITHUB_CLIENT_*`, CLI uses `GITHUB_CLI_*` only.
"""

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
    """Produce verifier + base64url SHA-256 challenge GitHub expects (`S256`)."""
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
    """Compose `https://github.com/login/oauth/authorize` query for the portal GitHub App."""
    cid = (settings.GITHUB_CLIENT_ID or "").strip()
    q = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "scope": scope,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(q)}"


def _github_oauth_credentials(app: str) -> tuple[str, str]:
    """Pick client id/secret pair: `web` portal app or `cli` loopback app."""
    if app == "cli":
        cid = getattr(settings, "GITHUB_CLI_CLIENT_ID", "").strip()
        secret = getattr(settings, "GITHUB_CLI_CLIENT_SECRET", "").strip()
        return cid, secret
    cid = (settings.GITHUB_CLIENT_ID or "").strip()
    secret = (settings.GITHUB_CLIENT_SECRET or "").strip()
    return cid, secret


def exchange_code_for_token(
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    app: str = "web",
) -> dict[str, Any]:
    """POST authorization code + PKCE verifier to GitHub and return JSON (`access_token`, ...)."""
    headers = {
        "Accept": "application/json",
    }
    client_id, secret = _github_oauth_credentials(app)
    data: dict[str, str] = {
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
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
    """Call `GET /user` with bearer token to retrieve GitHub profile payload."""
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
    """Create/update `accounts.User` keyed by GitHub numeric id and refresh profile fields."""
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
