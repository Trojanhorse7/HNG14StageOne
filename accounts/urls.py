"""Auth routes (not under /api/)."""

from django.urls import path

from accounts.views import (
    GitHubCallbackView,
    GitHubCliExchangeView,
    GitHubLoginRedirectView,
    LogoutView,
    RefreshTokenView,
)

urlpatterns = [
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
