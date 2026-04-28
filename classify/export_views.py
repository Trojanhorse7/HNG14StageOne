"""CSV export view for profiles."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO

from django.http import HttpResponse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsActiveInsightaUser
from classify.models import Profile
from classify.profile_filters import (
    ALLOWED_LIST_PARAMS,
    ERR_INVALID_QUERY,
    apply_filters,
    apply_sort,
    parse_list_query_params,
)


def _utc_iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class ProfileExportView(APIView):
    permission_classes = [IsActiveInsightaUser]

    def get(self, request: Request) -> HttpResponse | Response:
        fmt = request.query_params.get("format", "").strip().lower()
        if fmt != "csv":
            return Response(
                {"status": "error", "message": "Invalid or missing format parameter"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            parsed = parse_list_query_params(request.query_params)
        except ValueError as e:
            return Response(
                {"status": "error", "message": str(e) or ERR_INVALID_QUERY},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        sort_by = str(parsed.get("sort_by", "created_at"))
        order = str(parsed.get("order", "desc"))
        filter_keys = (
            "gender",
            "age_group",
            "country_id",
            "min_age",
            "max_age",
            "min_gender_probability",
            "min_country_probability",
        )
        fdict = {k: parsed[k] for k in filter_keys if k in parsed}

        qs = Profile.objects.all()
        qs = apply_filters(qs, fdict)
        qs = apply_sort(qs, sort_by, order)

        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "id",
            "name",
            "gender",
            "gender_probability",
            "age",
            "age_group",
            "country_id",
            "country_name",
            "country_probability",
            "created_at",
        ])

        for p in qs.iterator():
            writer.writerow([
                str(p.id),
                p.name,
                p.gender,
                p.gender_probability,
                p.age,
                p.age_group,
                p.country_id,
                p.country_name,
                p.country_probability,
                _utc_iso_z(p.created_at),
            ])

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"profiles_{timestamp}.csv"
        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
