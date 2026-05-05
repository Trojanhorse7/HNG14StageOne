"""DRF permissions: require active users by default; gate destructive APIs to admins."""


from __future__ import annotations

from rest_framework.permissions import BasePermission

from accounts.models import UserRole


class IsActiveInsightaUser(BasePermission):
    message = "Account is inactive"

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not getattr(user, "is_authenticated", False):
            return True
        return bool(getattr(user, "is_active", True))


class IsInsightaAdmin(BasePermission):
    message = "Forbidden"

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return getattr(user, "role", None) == UserRole.ADMIN
