"""Print access + refresh token pair for a user (submission / local testing)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from accounts.tokens import issue_token_pair


class Command(BaseCommand):
    help = (
        "Issue JWT access + opaque refresh for User.username (e.g. for grader forms). "
        "Does not print after this run — copy immediately."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "username",
            type=str,
            help="User.username / GitHub login (case-insensitive)",
        )

    def handle(self, *args, **options) -> None:
        raw = str(options["username"]).strip()
        if not raw:
            raise CommandError("username is required")
        try:
            user = User.objects.get(username__iexact=raw)
        except User.DoesNotExist as e:
            raise CommandError(f"No user with username matching {raw!r}") from e
        access, refresh = issue_token_pair(user)
        self.stdout.write(self.style.WARNING("Copy once; refresh is shown only here."))
        self.stdout.write(f"role={user.role}")
        self.stdout.write(f"access_token={access}")
        self.stdout.write(f"refresh_token={refresh}")
