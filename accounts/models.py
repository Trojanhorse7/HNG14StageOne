"""Insighta Labs+ users and refresh tokens (OAuth-only; no local passwords)."""

from __future__ import annotations

from django.db import models

from classify.uuid7 import new_uuid7


class UserRole(models.TextChoices):
    ADMIN = "admin", "admin"
    ANALYST = "analyst", "analyst"


class User(models.Model):
    id = models.UUIDField(primary_key=True, default=new_uuid7, editable=False)
    github_id = models.CharField(max_length=64, unique=True, db_index=True)
    username = models.CharField(max_length=255, unique=True)
    email = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(max_length=500, blank=True)
    role = models.CharField(
        max_length=32,
        choices=UserRole.choices,
        default=UserRole.ANALYST,
        db_index=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False


class RefreshToken(models.Model):
    """Opaque refresh token stored as SHA-256 hash; raw value is shown once to the client."""

    id = models.UUIDField(primary_key=True, default=new_uuid7, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="refresh_tokens"
    )
    token_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["token_hash", "revoked_at"]),
        ]


class GitHubOAuthState(models.Model):
    """Short-lived PKCE verifier bound to `state` for the browser (server-started) OAuth flow."""

    state = models.CharField(max_length=64, primary_key=True)
    code_verifier = models.CharField(max_length=128)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["expires_at"])]
