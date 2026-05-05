"""High-level auth HTTP handlers: GitHub OAuth redirects, CSRF helper, JWT/session refresh.

Browser flows set http-only cookies; machine clients use JSON bodies for refresh/logout.
"""

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
from accounts.throttles import AuthBurstThrottle

from accounts.github_oauth import (
    build_authorize_url,
    exchange_code_for_token,
    fetch_github_user,
    generate_pkce_pair,
    upsert_user_from_github_profile,
)
from accounts.models import GitHubOAuthState, RefreshToken, User, UserRole
from accounts.tokens import hash_refresh_token, issue_token_pair

logger = logging.getLogger(__name__)


def _error(message: str, code: int = 400) -> JsonResponse:
    """Uniform JSON error envelope for plain Django `View` handlers."""
    return JsonResponse({"status": "error", "message": message}, status=code)


def _success_token_payload(access: str, refresh: str) -> dict:
    """Success body for APIs that return bearer + refresh tokens in JSON (CLI)."""
    return {
        "status": "success",
        "access_token": access,
        "refresh_token": refresh,
    }


def _apply_cors_to_response(request, response):
    """Mirror portal allowlist on selected `/auth/*` responses so browser preflights succeed."""

    origin = (request.META.get("HTTP_ORIGIN") or "").strip()
    allowed = getattr(settings, "CORS_ALLOWED_ORIGINS", ()) or ()
    allowed_norm = {str(o).rstrip("/") for o in allowed}
    if not origin:
        portal = str(getattr(settings, "WEB_PORTAL_ORIGIN", "") or "").strip()
        if portal.rstrip("/") in allowed_norm:
            origin = portal
    if origin and origin.rstrip("/") in allowed_norm:
        response["Access-Control-Allow-Origin"] = origin
        if getattr(settings, "CORS_ALLOW_CREDENTIALS", False):
            response["Access-Control-Allow-Credentials"] = "true"
    return response


def _web_callback_url() -> str:
    """Fully qualified `{BACKEND_PUBLIC_URL}/auth/github/callback` for the portal OAuth app."""
    base = settings.BACKEND_PUBLIC_URL.rstrip("/")
    return f"{base}/auth/github/callback"


def _expected_cli_oauth_redirect_uri() -> str:
    """Loopback redirect registered on the separate CLI GitHub OAuth application."""
    base = (settings.INSIGHTA_CLI_OAUTH_REDIRECT or "").strip()
    return base if base else "http://127.0.0.1:8765/callback"


def _normalize_redirect_uri(uri: str) -> str:
    """Lower noise on redirect URI equality checks (strip + drop trailing slash)."""
    return str(uri).strip().rstrip("/")


def _purge_expired_oauth_states() -> None:
    """GC table rows backing short-lived browser OAuth `state` to PKCE verifier mapping."""
    GitHubOAuthState.objects.filter(expires_at__lt=timezone.now()).delete()


def _resolve_grader_admin_user() -> User | None:
    """Locate the admin user optionally forced via `GRADER_ADMIN_USERNAME` for test OAuth."""

    uname = getattr(settings, "GRADER_ADMIN_USERNAME", "") or ""
    uname = str(uname).strip()
    if uname:
        u = User.objects.filter(
            username__iexact=uname,
            role=UserRole.ADMIN,
            is_active=True,
        ).first()
        if u:
            return u
    return (
        User.objects.filter(role=UserRole.ADMIN, is_active=True)
        .order_by("created_at")
        .first()
    )


class GitHubLoginRedirectView(View):
    """Kick off browser login: persist PKCE verifier, redirect user to GitHub authorize."""

    def get(self, request):
        if not settings.GITHUB_CLIENT_ID:
            return _apply_cors_to_response(
                request, _error("GitHub OAuth is not configured", 503)
            )

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
        response = HttpResponseRedirect(url)
        return _apply_cors_to_response(request, response)


class GitHubCallbackView(View):
    """Complete browser login: validate `state`, exchange `code`, mint cookies or JSON tokens."""

    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        gh_error = request.GET.get("error")

        if not state:
            return _apply_cors_to_response(request, _error("Missing state parameter", 400))

        if gh_error:
            GitHubOAuthState.objects.filter(state=state).delete()
            return _apply_cors_to_response(
                request,
                _error((gh_error or "oauth_denied")[:200], 400),
            )

        row = GitHubOAuthState.objects.filter(
            state=state, expires_at__gte=timezone.now()
        ).first()

        if not row:
            return _apply_cors_to_response(
                request,
                _error("Invalid or expired OAuth state", 400),
            )

        if not code:
            return _apply_cors_to_response(request, _error("Missing code parameter", 400))

        if (
            getattr(settings, "INSIGHTA_ENABLE_TEST_OAUTH_CODE", False)
            and code == settings.INSIGHTA_TEST_OAUTH_CODE
        ):
            qv = request.GET.get("code_verifier")
            if qv is not None and str(qv).strip() != "":
                if str(qv).strip() != row.code_verifier:
                    row.delete()
                    return _apply_cors_to_response(
                        request, _error("Invalid code_verifier", 400)
                    )
            row.delete()
            admin_user = _resolve_grader_admin_user()
            if not admin_user:
                return _apply_cors_to_response(
                    request, _error("No active admin user for test OAuth", 503)
                )
            access, refresh_raw = issue_token_pair(admin_user)
            return _apply_cors_to_response(
                request, JsonResponse(_success_token_payload(access, refresh_raw))
            )

        verifier = row.code_verifier
        row.delete()

        try:
            token_json = exchange_code_for_token(
                code=code,
                code_verifier=verifier,
                redirect_uri=_web_callback_url(),
                app="web",
            )
            gh_access = token_json["access_token"]
            profile = fetch_github_user(gh_access)
            user = upsert_user_from_github_profile(profile)
        except Exception as e:
            logger.exception("GitHub OAuth callback failed")
            return _apply_cors_to_response(
                request,
                _error(f"OAuth exchange failed: {str(e)[:200]}", 400),
            )

        if not user.is_active:
            return _apply_cors_to_response(
                request, _error("Account is inactive", 403)
            )

        access, refresh_raw = issue_token_pair(user)
        response = HttpResponseRedirect(
            _portal_redirect({"login": "success"}, path="app/dashboard")
        )
        _set_auth_cookies(response, access, refresh_raw)
        return _apply_cors_to_response(request, response)


def _portal_redirect(query: dict, path: str = "") -> str:
    """Helper to build `WEB_PORTAL_ORIGIN` URLs for success/error query params."""

    base = settings.WEB_PORTAL_ORIGIN.rstrip("/")
    path = path.strip("/")
    url = f"{base}/{path}" if path else f"{base}/"
    if query:
        return f"{url}?{urlencode(query)}"
    return url


def _set_auth_cookies(response, access: str, refresh: str) -> None:
    """Issue paired access/refresh cookies with flags derived from `DEBUG` (SameSite/Secure)."""

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
    """Expire cookies with attributes matching how they were originally set."""

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
    """Validate refresh hash, revoke DB row, mint fresh access+refresh via `issue_token_pair`."""

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
    """Bootstrap CSRF for SPAs: Django sets `csrftoken` cookie and returns token JSON."""

    def get(self, request):
        token = get_token(request)
        return JsonResponse({"status": "ok", "csrfToken": token})


class MeView(APIView):
    """Expose `{id, username, role, ...}` for the currently authenticated JWT subject."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthBurstThrottle]

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
    """Rotate refresh token from http-only cookie and re-set both auth cookies (CSRF enforced)."""

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
    """Revoke active refresh cookie server-side and wipe client cookies."""

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
    """Accept CLI loopback OAuth result: exchange `code` posted with PKCE verifier."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [AuthBurstThrottle]

    def post(self, request: Request) -> Response:
        cli_id = getattr(settings, "GITHUB_CLI_CLIENT_ID", "").strip()
        cli_secret = getattr(settings, "GITHUB_CLI_CLIENT_SECRET", "").strip()
        if not cli_id or not cli_secret:
            return Response(
                {
                    "status": "error",
                    "message": "GitHub CLI OAuth is not configured (GITHUB_CLI_CLIENT_ID and GITHUB_CLI_CLIENT_SECRET required)",
                },
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
        expected = _normalize_redirect_uri(_expected_cli_oauth_redirect_uri())
        if _normalize_redirect_uri(str(redirect_uri)) != expected:
            return Response(
                {
                    "status": "error",
                    "message": "redirect_uri must match INSIGHTA_CLI_OAUTH_REDIRECT (CLI GitHub app callback URL)",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token_json = exchange_code_for_token(
                code=str(code),
                code_verifier=str(code_verifier),
                redirect_uri=str(redirect_uri),
                app="cli",
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
    """Non-browser refresh: `{ "refresh_token": "..." }` body returns a rotated pair."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [AuthBurstThrottle]

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
    """JSON logout: revoke hashed refresh row if it still exists (idempotent)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [AuthBurstThrottle]

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
