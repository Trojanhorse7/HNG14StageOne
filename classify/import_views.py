"""Streaming CSV import: parse uploaded rows in chunks and persist without loading whole file.

Admin-only; bumps profile query cache generation when rows are successfully applied.
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsActiveInsightaUser, IsInsightaAdmin
from classify.filter_canonical import bump_profile_query_cache_generation
from classify.models import Profile

CORE_FIELDS = (
    "name",
    "gender",
    "gender_probability",
    "age",
    "age_group",
    "country_id",
    "country_name",
    "country_probability",
)

OPTIONAL_EXPORT_FIELDS = frozenset({"id", "created_at"})

_ALLOWED_GENDER = frozenset({"male", "female"})
_ALLOWED_AGE_GROUP = frozenset({"child", "teenager", "adult", "senior"})
_BATCH_SIZE = 2000


class ProfileCsvImportView(APIView):
    """POST multipart `file` (UTF-8 CSV); bulk_create Profile rows with per-batch dedupe + reasons."""

    permission_classes = [IsActiveInsightaUser, IsInsightaAdmin]
    parser_classes = [MultiPartParser]

    def post(self, request: Request) -> Response:
        """Stream CSV, validate rows, batch insert, return inserted/skipped breakdown; bumps cache gen."""

        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"status": "error", "message": "Missing multipart file field 'file'"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ctype = (getattr(upload, "content_type", None) or "").lower()
        if ctype and "csv" not in ctype and ctype not in (
            "text/plain",
            "application/vnd.ms-excel",
            "application/octet-stream",
        ):
            return Response(
                {"status": "error", "message": "Expected a CSV file (field 'file')"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reasons: dict[str, int] = defaultdict(int)
        total_rows = 0
        inserted = 0
        skipped = 0
        seen_names: set[str] = set()
        batch: list[Profile] = []

        def flush() -> None:
            nonlocal batch, inserted, skipped
            if not batch:
                return
            names = [p.name for p in batch]
            existing_db = set(
                Profile.objects.filter(name__in=names).values_list("name", flat=True)
            )
            to_create: list[Profile] = []
            for p in batch:
                if p.name in existing_db:
                    reasons["duplicate_name"] += 1
                    skipped += 1
                    continue
                to_create.append(p)
            batch.clear()
            if not to_create:
                return
            try:
                with transaction.atomic():
                    Profile.objects.bulk_create(
                        to_create,
                        batch_size=_BATCH_SIZE,
                        ignore_conflicts=False,
                    )
            except IntegrityError:
                for p in to_create:
                    try:
                        with transaction.atomic():
                            p.save(force_insert=True)
                    except IntegrityError:
                        reasons["duplicate_name"] += 1
                        skipped += 1
                    else:
                        inserted += 1
                return
            inserted += len(to_create)

        def parse_header(header_row: list[str]) -> dict[str, int] | None:
            idx: dict[str, int] = {}
            for i, h in enumerate(header_row):
                key = (h or "").strip().lower()
                if key in OPTIONAL_EXPORT_FIELDS:
                    continue
                idx[key] = i
            for f in CORE_FIELDS:
                if f not in idx:
                    return None
            return idx

        upload.open("rb")
        text_fp = io.TextIOWrapper(upload, encoding="utf-8-sig", newline="")
        try:
            try:
                reader = csv.reader(text_fp)

                try:
                    header_raw = next(reader)
                except StopIteration:
                    bump_profile_query_cache_generation()
                    return Response(
                        {
                            "status": "success",
                            "total_rows": 0,
                            "inserted": 0,
                            "skipped": 0,
                            "reasons": {},
                        },
                        status=status.HTTP_200_OK,
                    )

                col_idx = parse_header([x.strip() for x in header_raw])
                if col_idx is None:
                    return Response(
                        {
                            "status": "error",
                            "message": "CSV header must include all required columns",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                header_len = len(header_raw)

                def cell(row: list[str], field: str) -> str:
                    j = col_idx[field]
                    return row[j].strip() if j < len(row) else ""

                for row in reader:
                    total_rows += 1
                    if len(row) != header_len:
                        reasons["malformed_row"] += 1
                        skipped += 1
                        continue

                    name = cell(row, "name")
                    if not name:
                        reasons["missing_fields"] += 1
                        skipped += 1
                        continue
                    if name in seen_names:
                        reasons["duplicate_name"] += 1
                        skipped += 1
                        continue

                    g_raw = cell(row, "gender").lower()
                    if g_raw not in _ALLOWED_GENDER:
                        reasons["invalid_gender"] += 1
                        skipped += 1
                        continue

                    ag = cell(row, "age_group").lower()
                    if ag not in _ALLOWED_AGE_GROUP:
                        reasons["invalid_age_group"] += 1
                        skipped += 1
                        continue

                    try:
                        age = int(cell(row, "age"))
                    except (TypeError, ValueError):
                        reasons["invalid_age"] += 1
                        skipped += 1
                        continue
                    if age < 1 or age > 149:
                        reasons["invalid_age"] += 1
                        skipped += 1
                        continue

                    cid = cell(row, "country_id").strip().upper()
                    if not re.fullmatch(r"[A-Z]{2}", cid):
                        reasons["invalid_country"] += 1
                        skipped += 1
                        continue

                    gp_s, cp_s = cell(row, "gender_probability"), cell(
                        row, "country_probability"
                    )
                    try:
                        gp = float(gp_s) if gp_s != "" else 0.0
                        cp = float(cp_s) if cp_s != "" else 0.0
                    except (TypeError, ValueError):
                        reasons["invalid_probability"] += 1
                        skipped += 1
                        continue
                    if gp < 0 or gp > 1 or cp < 0 or cp > 1:
                        reasons["invalid_probability"] += 1
                        skipped += 1
                        continue

                    seen_names.add(name)
                    batch.append(
                        Profile(
                            name=name,
                            gender=g_raw,
                            gender_probability=gp,
                            age=age,
                            age_group=ag,
                            country_id=cid,
                            country_name=cell(row, "country_name"),
                            country_probability=cp,
                        )
                    )
                    if len(batch) >= _BATCH_SIZE:
                        flush()
                flush()
            except UnicodeDecodeError:
                return Response(
                    {
                        "status": "error",
                        "message": "CSV must be valid UTF-8 (with optional BOM)",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            finally:
                text_fp.detach()
        finally:
            upload.close()

        bump_profile_query_cache_generation()
        out_reasons = {k: int(v) for k, v in sorted(reasons.items()) if v}
        return Response(
            {
                "status": "success",
                "total_rows": total_rows,
                "inserted": inserted,
                "skipped": skipped,
                "reasons": out_reasons,
            },
            status=status.HTTP_200_OK,
        )
