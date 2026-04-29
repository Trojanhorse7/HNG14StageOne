"""GitHub OAuth (PKCE), token refresh, and logout."""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import JWTAuthentication

from accounts.github_oauth import (
    build_authorize_url,
    exchange_code_for_token,
    fetch_github_user,
    generate_pkce_pair,
    upsert_user_from_github_profile,
)
from accounts.models import GitHubOAuthState, RefreshToken, User
from accounts.tokens import hash_refresh_token, issue_token_pair

logger = logging.getLogger(__name__)


def _error(message: str, code: int = 400) -> JsonResponse:
    return JsonResponse({"status": "error", "message": message}, status=code)


def _success_token_payload(access: str, refresh: str) -> dict:
    return {
        "status": "success",
        "access_token": access,
        "refresh_token": refresh,
    }


def _web_callback_url() -> str:
    base = settings.BACKEND_PUBLIC_URL.rstrip("/")
    return f"{base}/auth/github/callback"


def _purge_expired_oauth_states() -> None:
    GitHubOAuthState.objects.filter(expires_at__lt=timezone.now()).delete()


class GitHubLoginRedirectView(View):
    """Start browser OAuth: store PKCE verifier server-side, redirect to GitHub."""

    def get(self, request):
        if not settings.GITHUB_CLIENT_ID:
            return _error("GitHub OAuth is not configured", 503)

        _purge_expired_oauth_states()
        state = secrets.token_urlsafe(32)
        verifier, challenge = generate_pkce_pair()
        GitHubOAuthState.objects.create(
            state=state,
            code_verifier=verifier,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        url = build_authorize_url(
            redirect_uri=_web_callback_url(),
            state=state,
            code_challenge=challenge,
        )
        return HttpResponseRedirect(url)


class GitHubCallbackView(View):
    """GitHub redirects here with ?code=&state=; exchange code, set cookies, redirect to portal."""

    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        if not code or not state:
            return HttpResponseRedirect(
                _portal_redirect({"error": "missing_code_or_state"})
            )

        row = GitHubOAuthState.objects.filter(
            state=state, expires_at__gte=timezone.now()
        ).first()
        if not row:
            return HttpResponseRedirect(_portal_redirect({"error": "invalid_state"}))

        verifier = row.code_verifier
        row.delete()

        try:
            token_json = exchange_code_for_token(
                code=code,
                code_verifier=verifier,
                redirect_uri=_web_callback_url(),
            )
            gh_access = token_json["access_token"]
            profile = fetch_github_user(gh_access)
            user = upsert_user_from_github_profile(profile)
        except Exception as e:
            logger.exception("GitHub OAuth callback failed")
            return HttpResponseRedirect(
                _portal_redirect({"error": "oauth_failed", "detail": str(e)[:120]})
            )

        if not user.is_active:
            return HttpResponseRedirect(_portal_redirect({"error": "account_inactive"}))

        access, refresh_raw = issue_token_pair(user)
        response = HttpResponseRedirect(_portal_redirect({"login": "success"}))
        _set_auth_cookies(response, access, refresh_raw)
        return response


def _portal_redirect(query: dict) -> str:
    base = settings.WEB_PORTAL_ORIGIN.rstrip("/")
    if not query:
        return f"{base}/"
    return f"{base}/?{urlencode(query)}"


def _set_auth_cookies(response, access: str, refresh: str) -> None:
    """Attach http-only auth cookies. Production uses None+Secure for cross-origin SPA fetch."""
    if settings.DEBUG:
        secure = False
        samesite = "Lax"
    else:
        secure = True
        samesite = "None"
    response.set_cookie(
        "insighta_access",
        access,
        max_age=settings.ACCESS_TOKEN_LIFETIME_SECONDS,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )
    response.set_cookie(
        "insighta_refresh",
        refresh,
        max_age=settings.REFRESH_TOKEN_LIFETIME_SECONDS,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )


def _delete_auth_cookies(response) -> None:
    """Clear auth cookies with matching flags so browsers drop cross-site cookies."""
    if settings.DEBUG:
        response.delete_cookie("insighta_access", path="/")
        response.delete_cookie("insighta_refresh", path="/")
    else:
        response.delete_cookie(
            "insighta_access",
            path="/",
            samesite="None",
        )
        response.delete_cookie(
            "insighta_refresh",
            path="/",
            samesite="None",
        )


def _perform_refresh_rotation(raw_refresh: str) -> tuple[str, str] | None:
    """Return (access, refresh) or None if invalid."""
    digest = hash_refresh_token(str(raw_refresh).strip())
    now = timezone.now()
    row = (
        RefreshToken.objects.filter(
            token_hash=digest,
            revoked_at__isnull=True,
            expires_at__gt=now,
        )
        .select_related("user")
        .first()
    )
    if not row:
        return None
    user = row.user
    if not user.is_active:
        return None
    row.revoked_at = now
    row.save(update_fields=["revoked_at"])
    access, refresh_raw = issue_token_pair(user)
    return access, refresh_raw


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfCookieView(View):
    """
    GET: set `csrftoken` cookie and return the token for X-CSRFToken.
    Cross-origin SPAs cannot read the cookie via document.cookie; they use `csrfToken` in JSON.
    """

    def get(self, request):
        token = get_token(request)
        return JsonResponse({"status": "ok", "csrfToken": token})


class MeView(APIView):
    """Current user from JWT (cookie or Bearer)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        u: User = request.user
        return Response(
            {
                "status": "success",
                "data": {
                    "id": str(u.id),
                    "username": u.username,
                    "email": u.email,
                    "role": u.role,
                    "avatar_url": u.avatar_url,
                    "github_id": u.github_id,
                    "is_active": u.is_active,
                },
            }
        )


class WebRefreshView(View):
    """
    Browser-only refresh: read `insighta_refresh` http-only cookie, rotate, set new cookies.
    CSRF required (not exempt).
    """

    def post(self, request):
        raw = request.COOKIES.get("insighta_refresh")
        if not raw:
            return JsonResponse(
                {"status": "error", "message": "Missing refresh cookie"},
                status=401,
            )
        pair = _perform_refresh_rotation(raw)
        if not pair:
            return JsonResponse(
                {"status": "error", "message": "Invalid or expired refresh token"},
                status=401,
            )
        access, refresh_raw = pair
        response = JsonResponse({"status": "success"})
        _set_auth_cookies(response, access, refresh_raw)
        return response


class WebLogoutView(View):
    """Revoke refresh from cookie and clear auth cookies. CSRF required."""

    def post(self, request):
        raw = request.COOKIES.get("insighta_refresh")
        if raw:
            digest = hash_refresh_token(str(raw).strip())
            RefreshToken.objects.filter(
                token_hash=digest, revoked_at__isnull=True
            ).update(revoked_at=timezone.now())
        response = JsonResponse({"status": "success"})
        _delete_auth_cookies(response)
        return response


@method_decorator(csrf_exempt, name="dispatch")
class GitHubCliExchangeView(APIView):
    """
    CLI completes OAuth: localhost captures ?code=&state=, then POSTs here with
    the same code_verifier that was used in the authorize URL (CLI-generated flow).

    Request JSON: code, code_verifier, redirect_uri (must match GitHub App callback).
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        if not settings.GITHUB_CLIENT_ID:
            return Response(
                {"status": "error", "message": "GitHub OAuth is not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        code = request.data.get("code")
        code_verifier = request.data.get("code_verifier")
        redirect_uri = request.data.get("redirect_uri")
        if not code or not code_verifier or not redirect_uri:
            return Response(
                {"status": "error", "message": "Missing or empty parameter"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token_json = exchange_code_for_token(
                code=str(code),
                code_verifier=str(code_verifier),
                redirect_uri=str(redirect_uri),
            )
            gh_access = token_json["access_token"]
            profile = fetch_github_user(gh_access)
            user = upsert_user_from_github_profile(profile)
        except Exception as e:
            logger.exception("CLI GitHub exchange failed")
            return Response(
                {"status": "error", "message": str(e) or "OAuth exchange failed"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        if not user.is_active:
            return Response(
                {"status": "error", "message": "Account is inactive"},
                status=status.HTTP_403_FORBIDDEN,
            )

        access, refresh_raw = issue_token_pair(user)
        return Response(_success_token_payload(access, refresh_raw))


@method_decorator(csrf_exempt, name="dispatch")
class RefreshTokenView(APIView):
    """Rotate refresh token: old refresh invalidated immediately; new pair returned."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        raw = request.data.get("refresh_token")
        if raw is None or str(raw).strip() == "":
            return Response(
                {"status": "error", "message": "Missing or empty parameter"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        pair = _perform_refresh_rotation(str(raw).strip())
        if not pair:
            return Response(
                {"status": "error", "message": "Invalid or expired refresh token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        access, refresh_raw = pair
        return Response(_success_token_payload(access, refresh_raw))


@method_decorator(csrf_exempt, name="dispatch")
class LogoutView(APIView):
    """Revoke one refresh token (server-side)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        raw = request.data.get("refresh_token")
        if raw is None or str(raw).strip() == "":
            return Response(
                {"status": "error", "message": "Missing or empty parameter"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        digest = hash_refresh_token(str(raw).strip())
        updated = RefreshToken.objects.filter(
            token_hash=digest, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
        if not updated:
            return Response(
                {"status": "error", "message": "Invalid refresh token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response({"status": "success"})
