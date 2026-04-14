"""CRUD API for persisted profiles (HNG Stage 1)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from classify.models import Profile
from classify.profile_service import aggregate_for_name

ERR_MISSING_NAME = "Missing or empty name"
ERR_NAME_TYPE = "Invalid type"
ERR_NOT_FOUND = "Profile not found"


def _utc_iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _full_profile_dict(p: Profile) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "gender": p.gender,
        "gender_probability": p.gender_probability,
        "sample_size": p.sample_size,
        "age": p.age,
        "age_group": p.age_group,
        "country_id": p.country_id,
        "country_probability": p.country_probability,
        "created_at": _utc_iso_z(p.created_at),
    }


def _list_item_dict(p: Profile) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "gender": p.gender,
        "age": p.age,
        "age_group": p.age_group,
        "country_id": p.country_id,
    }


def _parse_name_from_body(data) -> tuple[str | None, Response | None]:
    if not isinstance(data, dict):
        return None, Response(
            {"status": "error", "message": ERR_NAME_TYPE},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if "name" not in data:
        return None, Response(
            {"status": "error", "message": ERR_MISSING_NAME},
            status=status.HTTP_400_BAD_REQUEST,
        )
    raw = data.get("name")
    if raw is None:
        return None, Response(
            {"status": "error", "message": ERR_MISSING_NAME},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not isinstance(raw, str):
        return None, Response(
            {"status": "error", "message": ERR_NAME_TYPE},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    name = raw.strip()
    if not name:
        return None, Response(
            {"status": "error", "message": ERR_MISSING_NAME},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return name, None


class ProfileListCreateView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        qs = Profile.objects.all()
        gender = request.query_params.get("gender")
        country_id = request.query_params.get("country_id")
        age_group = request.query_params.get("age_group")
        if gender:
            qs = qs.filter(gender__iexact=gender.strip())
        if country_id:
            qs = qs.filter(country_id__iexact=country_id.strip())
        if age_group:
            qs = qs.filter(age_group__iexact=age_group.strip())
        items = [_list_item_dict(p) for p in qs]
        return Response(
            {"status": "success", "count": len(items), "data": items},
            status=status.HTTP_200_OK,
        )

    def post(self, request: Request) -> Response:
        name, err = _parse_name_from_body(request.data)
        if err:
            return err

        key = name.lower()
        existing = Profile.objects.filter(name_normalized=key).first()
        if existing:
            return Response(
                {
                    "status": "success",
                    "message": "Profile already exists",
                    "data": _full_profile_dict(existing),
                },
                status=status.HTTP_200_OK,
            )

        aggregated, upstream_err = aggregate_for_name(name)
        if upstream_err:
            return Response(upstream_err, status=status.HTTP_502_BAD_GATEWAY)

        try:
            with transaction.atomic():
                profile = Profile.objects.create(
                    name=name,
                    name_normalized=key,
                    gender=aggregated.gender,
                    gender_probability=aggregated.gender_probability,
                    sample_size=aggregated.sample_size,
                    age=aggregated.age,
                    age_group=aggregated.age_group,
                    country_id=aggregated.country_id,
                    country_probability=aggregated.country_probability,
                )
        except IntegrityError:
            existing = Profile.objects.filter(name_normalized=key).first()
            if existing:
                return Response(
                    {
                        "status": "success",
                        "message": "Profile already exists",
                        "data": _full_profile_dict(existing),
                    },
                    status=status.HTTP_200_OK,
                )
            return Response(
                {"status": "error", "message": "Server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {"status": "success", "data": _full_profile_dict(profile)},
            status=status.HTTP_201_CREATED,
        )


class ProfileDetailView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request, profile_id: str) -> Response:
        try:
            pk = uuid.UUID(str(profile_id))
        except (ValueError, TypeError):
            return Response(
                {"status": "error", "message": ERR_NOT_FOUND},
                status=status.HTTP_404_NOT_FOUND,
            )
        profile = Profile.objects.filter(pk=pk).first()
        if not profile:
            return Response(
                {"status": "error", "message": ERR_NOT_FOUND},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {"status": "success", "data": _full_profile_dict(profile)},
            status=status.HTTP_200_OK,
        )

    def delete(self, request: Request, profile_id: str) -> Response:
        try:
            pk = uuid.UUID(str(profile_id))
        except (ValueError, TypeError):
            return Response(
                {"status": "error", "message": ERR_NOT_FOUND},
                status=status.HTTP_404_NOT_FOUND,
            )
        deleted, _ = Profile.objects.filter(pk=pk).delete()
        if not deleted:
            return Response(
                {"status": "error", "message": ERR_NOT_FOUND},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
