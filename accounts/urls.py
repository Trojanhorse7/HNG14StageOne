"""Auth routes (not under /api/)."""

from django.urls import path

from accounts.views import (
    CsrfCookieView,
    GitHubCallbackView,
    GitHubCliExchangeView,
    GitHubLoginRedirectView,
    LogoutView,
    MeView,
    RefreshTokenView,
    WebLogoutView,
    WebRefreshView,
)

urlpatterns = [
    path("auth/csrf", CsrfCookieView.as_view()),
    path("auth/csrf/", CsrfCookieView.as_view()),
    path("auth/me", MeView.as_view()),
    path("auth/me/", MeView.as_view()),
    path("auth/refresh/web", WebRefreshView.as_view()),
    path("auth/refresh/web/", WebRefreshView.as_view()),
    path("auth/logout/web", WebLogoutView.as_view()),
    path("auth/logout/web/", WebLogoutView.as_view()),
    path("auth/github", GitHubLoginRedirectView.as_view()),
    path("auth/github/", GitHubLoginRedirectView.as_view()),
    path("auth/github/callback", GitHubCallbackView.as_view()),
    path("auth/github/callback/", GitHubCallbackView.as_view()),
    path("auth/github/cli", GitHubCliExchangeView.as_view()),
    path("auth/github/cli/", GitHubCliExchangeView.as_view()),
    path("auth/refresh", RefreshTokenView.as_view()),
    path("auth/refresh/", RefreshTokenView.as_view()),
    path("auth/logout", LogoutView.as_view()),
    path("auth/logout/", LogoutView.as_view()),
]
