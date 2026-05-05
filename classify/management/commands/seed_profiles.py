"""Bulk seed/update helper with Postgres-friendly batching and timeout backoff.

Reads `profiles` array (or top-level list) from JSON; matches existing rows by unique `name`.
"""

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection
from django.db.utils import OperationalError

from classify.models import Profile
from classify.uuid7 import new_uuid7

BATCH_DEFAULT = 400
# Hosted Postgres often limits rows per statement — override via `SEED_POSTGRES_BATCH` or `--batch`.
BATCH_POSTGRES_DEFAULT = 250

_UPDATE_FIELDS = [
    "gender",
    "gender_probability",
    "age",
    "age_group",
    "country_id",
    "country_name",
    "country_probability",
]


def _pg_batch_size(cli_batch: int | None) -> int:
    """Derive insert/update chunk size from CLI flag or env, capped at 2000 rows."""
    if cli_batch is not None and cli_batch > 0:
        return min(cli_batch, 2000)
    raw = os.environ.get("SEED_POSTGRES_BATCH", str(BATCH_POSTGRES_DEFAULT))
    try:
        b = int(raw.strip())
    except (TypeError, ValueError):
        b = BATCH_POSTGRES_DEFAULT
    return max(1, min(b, 2000))


def _relax_postgres_timeouts() -> None:
    """Best-effort disable statement/lock timeouts for long seed runs (Postgres only)."""
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        try:
            cursor.execute("SET statement_timeout = 0")
            cursor.execute("SET lock_timeout = 0")
        except Exception:
            pass


def _bulk_create_adaptive(
    instances: list[Profile],
    *,
    start_batch: int,
    log,
) -> None:
    """Insert new rows using decreasing batch sizes when the database reports timeouts."""
    if not instances:
        return
    if connection.vendor != "postgresql":
        for j in range(0, len(instances), BATCH_DEFAULT):
            chunk = instances[j : j + BATCH_DEFAULT]
            Profile.objects.bulk_create(chunk, batch_size=BATCH_DEFAULT)
        return
    i = 0
    batch = start_batch
    while i < len(instances):
        chunk = instances[i : i + batch]
        try:
            Profile.objects.bulk_create(
                chunk, batch_size=max(1, min(batch, len(chunk)))
            )
            i += len(chunk)
            batch = start_batch
        except OperationalError as e:
            err = str(e).lower()
            if "timeout" not in err and "canceled" not in err and "querycanceled" not in err:
                raise
            if batch <= 1:
                log(
                    f"Seeding: single-row insert also failed (DB limit still hit). {e}",
                    is_error=True,
                )
                raise
            nbatch = max(1, batch // 2)
            log(
                f"Seeding: statement timeout on batch of {len(chunk)}; retrying with batch size {nbatch}."
            )
            batch = nbatch


def _bulk_update_adaptive(
    instances: list[Profile],
    *,
    start_batch: int,
    log,
) -> None:
    """Same adaptive strategy as inserts but targeting `bulk_update` field list."""
    if not instances:
        return
    if connection.vendor != "postgresql":
        for j in range(0, len(instances), BATCH_DEFAULT):
            chunk = instances[j : j + BATCH_DEFAULT]
            Profile.objects.bulk_update(
                chunk, fields=_UPDATE_FIELDS, batch_size=BATCH_DEFAULT
            )
        return
    i = 0
    batch = start_batch
    while i < len(instances):
        chunk = instances[i : i + batch]
        try:
            Profile.objects.bulk_update(
                chunk, fields=_UPDATE_FIELDS, batch_size=max(1, min(batch, len(chunk)))
            )
            i += len(chunk)
            batch = start_batch
        except OperationalError as e:
            err = str(e).lower()
            if "timeout" not in err and "canceled" not in err and "querycanceled" not in err:
                raise
            if batch <= 1:
                log(
                    f"Seeding: single-row update also failed. {e}",
                    is_error=True,
                )
                raise
            nbatch = max(1, batch // 2)
            log(
                f"Seeding: timeout on update batch of {len(chunk)}; retrying with batch size {nbatch}."
            )
            batch = nbatch


class Command(BaseCommand):
    """Django entrypoint invoked as `manage.py seed_profiles`."""

    help = "Seed the database with profiles from seed_profiles.json (re-runs update by name)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--path",
            type=str,
            default=None,
            help="Path to JSON (default: seed_profiles.json in project root).",
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=None,
            metavar="N",
            help="Postgres: rows per INSERT/UPDATE (default env SEED_POSTGRES_BATCH or 250).",
        )

    def _log(self, msg: str, is_error: bool = False) -> None:
        if is_error:
            self.stderr.write(msg)
        else:
            self.stdout.write(msg)

    def handle(self, *args, **options) -> None:
        close_old_connections()
        _relax_postgres_timeouts()
        start_batch = (
            _pg_batch_size(options.get("batch"))
            if connection.vendor == "postgresql"
            else BATCH_DEFAULT
        )
        if connection.vendor == "postgresql":
            self.stdout.write(
                f"Seeding: Postgres batch size = {start_batch} "
                f"(set SEED_POSTGRES_BATCH or --batch to tune).\n"
            )

        base = Path(__file__).resolve().parent.parent.parent.parent
        path = Path(options["path"]) if options["path"] else base / "seed_profiles.json"
        if not path.is_file():
            self.stderr.write(f"File not found: {path}")
            return
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("profiles") or data
        if not isinstance(rows, list):
            self.stderr.write("Invalid JSON: expected a list or {profiles: []}")
            return

        by_name: dict[str, Profile] = {p.name: p for p in Profile.objects.all()}

        to_create: list[Profile] = []
        to_update: list[Profile] = []

        n = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            if not name:
                continue
            name = str(name).strip()
            field_values = {
                "gender": str(row.get("gender", "")).lower(),
                "gender_probability": float(row["gender_probability"]),
                "age": int(row["age"]),
                "age_group": str(row.get("age_group", "")).lower(),
                "country_id": str(row.get("country_id", ""))[:2].upper(),
                "country_name": str(row.get("country_name", "")),
                "country_probability": float(row["country_probability"]),
            }
            n += 1
            if name in by_name:
                p = by_name[name]
                for k, v in field_values.items():
                    setattr(p, k, v)
                to_update.append(p)
            else:
                to_create.append(
                    Profile(
                        id=new_uuid7(),
                        name=name,
                        **field_values,
                    )
                )

        # Each bulk_* call is independent so half-size retries do not poison earlier chunks.
        _bulk_create_adaptive(to_create, start_batch=start_batch, log=self._log)
        _bulk_update_adaptive(to_update, start_batch=start_batch, log=self._log)

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {n} profile rows: "
                f"{len(to_create)} created, {len(to_update)} updated (by name)."
            )
        )
