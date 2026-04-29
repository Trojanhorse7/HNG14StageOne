"""One-off: set Insighta user role by GitHub username (User.username)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User, UserRole


class Command(BaseCommand):
    help = "Set role for a user (matches User.username case-insensitively, e.g. GitHub login)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "username",
            type=str,
            help="User.username / GitHub login",
        )
        parser.add_argument(
            "--role",
            choices=[UserRole.ADMIN, UserRole.ANALYST],
            default=UserRole.ADMIN,
            help=f"Target role (default: {UserRole.ADMIN})",
        )

    def handle(self, *args, **options) -> None:
        raw = str(options["username"]).strip()
        if not raw:
            raise CommandError("username is required")
        role = options["role"]
        try:
            user = User.objects.get(username__iexact=raw)
        except User.DoesNotExist as e:
            raise CommandError(f"No user with username matching {raw!r}") from e
        user.role = role
        user.save(update_fields=["role"])
        self.stdout.write(
            self.style.SUCCESS(f"Updated {user.username!r} -> role={role!r}")
        )
