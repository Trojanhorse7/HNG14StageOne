"""REST views for profile collection, natural-language search, detail, and cache-aware list reads.

List + search responses are cached briefly; admin create/delete/import bump the cache generation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from django.core.cache import cache
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsActiveInsightaUser, IsInsightaAdmin
from classify.filter_canonical import (
    bump_profile_query_cache_generation,
    canonical_filters,
    profile_list_search_cache_key,
)
from classify.models import Profile
from classify.nl_query import parse_nl_query
from classify.pagination_links import build_pagination_links, total_pages_count
from classify.profile_filters import (
    ALLOWED_LIST_PARAMS,
    ALLOWED_SEARCH_PARAMS,
    ERR_BAD_REQUEST,
    ERR_INVALID_QUERY,
    apply_filters,
    apply_sort,
    parse_list_query_params,
    parse_search_query_params,
)
from classify.profile_service import aggregate_for_name

ERR_MISSING_NAME = "Missing or empty name"
ERR_NAME_TYPE = "Invalid type"
ERR_NOT_FOUND = "Profile not found"
ERR_UNABLE_INTERPRET = "Unable to interpret query"

LIST_PATH = "/api/profiles"
SEARCH_PATH = "/api/profiles/search"
LIST_SEARCH_CACHE_TIMEOUT = 90  # Keep in sync with settings.CACHES["default"]["TIMEOUT"]


def _utc_iso_z(dt: datetime) -> str:
    """Format aware datetimes as UTC ISO-8601 with Z suffix for JSON payloads."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _full_profile_dict(p: Profile) -> dict:
    """Serialize a Profile ORM row to the public API `data` object shape."""
    return {
        "id": str(p.id),
        "name": p.name,
        "gender": p.gender,
        "gender_probability": p.gender_probability,
        "age": p.age,
        "age_group": p.age_group,
        "country_id": p.country_id,
        "country_name": p.country_name,
        "country_probability": p.country_probability,
        "created_at": _utc_iso_z(p.created_at),
    }


def _parse_name_from_body(data) -> tuple[str | None, Response | None]:
    """Extract non-empty string `name` from JSON body or return an error Response."""
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
    """GET `/api/profiles` (filtered list + pagination) or POST admin create via upstream aggregate APIs."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [
                IsActiveInsightaUser(),
                IsInsightaAdmin(),
            ]
        return [IsActiveInsightaUser()]

    def get(self, request: Request) -> Response:
        """Return cached page if present else query DB, serialize, and populate shared cache."""
        try:
            parsed = parse_list_query_params(request.query_params)
        except ValueError as e:
            return Response(
                {"status": "error", "message": str(e) or ERR_INVALID_QUERY},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        page = int(parsed.get("page", 1))
        limit = int(parsed.get("limit", 10))
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

        cache_key = profile_list_search_cache_key(
            kind="list",
            filters_json=canonical_filters(fdict),
            page=page,
            limit=limit,
            sort_by=sort_by,
            order=order,
        )
        hit = cache.get(cache_key)
        if hit is not None:
            return Response(hit, status=status.HTTP_200_OK)

        qs = Profile.objects.all()
        qs = apply_filters(qs, fdict)
        total = qs.count()
        qs = apply_sort(qs, sort_by, order)
        start = (page - 1) * limit
        rows = list(qs[start : start + limit])
        links = build_pagination_links(
            path=LIST_PATH,
            query_params=request.query_params,
            param_keys=ALLOWED_LIST_PARAMS,
            page=page,
            limit=limit,
            total=total,
        )
        payload = {
            "status": "success",
            "page": int(page),
            "limit": int(limit),
            "total": int(total),
            "total_pages": int(total_pages_count(total, limit)),
            "links": links,
            "data": [_full_profile_dict(p) for p in rows],
        }
        cache.set(cache_key, payload, timeout=LIST_SEARCH_CACHE_TIMEOUT)
        return Response(
            payload,
            status=status.HTTP_200_OK,
        )

    def post(self, request: Request) -> Response:
        """Create Profile from Genderize/Agify/Nationalize aggregation; idempotent on duplicate name."""

        if err:
            return err

        existing = Profile.objects.filter(name=name).first()
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
            msg = upstream_err.get("message", "Upstream error")
            return Response(
                {"status": "error", "message": msg},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            with transaction.atomic():
                profile = Profile.objects.create(
                    name=name,
                    gender=aggregated.gender,
                    gender_probability=aggregated.gender_probability,
                    age=aggregated.age,
                    age_group=aggregated.age_group,
                    country_id=aggregated.country_id,
                    country_name=aggregated.country_name,
                    country_probability=aggregated.country_probability,
                )
        except IntegrityError:
            again = Profile.objects.filter(name=name).first()
            if again:
                return Response(
                    {
                        "status": "success",
                        "message": "Profile already exists",
                        "data": _full_profile_dict(again),
                    },
                    status=status.HTTP_200_OK,
                )
            return Response(
                {"status": "error", "message": "Server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        bump_profile_query_cache_generation()
        return Response(
            {"status": "success", "data": _full_profile_dict(profile)},
            status=status.HTTP_201_CREATED,
        )


class ProfileSearchView(APIView):
    """GET `/api/profiles/search`: turns `q` into filters, then same list+cache path as collection."""

    def get(self, request: Request) -> Response:
        """Parse NL into filters, serve from cache or DB, cache successful JSON for this page."""
        try:
            parsed = parse_search_query_params(request.query_params)
        except ValueError as e:
            return Response(
                {"status": "error", "message": str(e) or ERR_INVALID_QUERY},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        q = parsed.get("q")
        if q is None or str(q).strip() == "":
            return Response(
                {"status": "error", "message": ERR_BAD_REQUEST},
                status=status.HTTP_400_BAD_REQUEST,
            )
        page = int(parsed.get("page", 1))
        limit = int(parsed.get("limit", 10))
        sort_by = "created_at"
        order = "desc"

        flt = parse_nl_query(str(q))
        if flt is None:
            return Response(
                {"status": "error", "message": ERR_UNABLE_INTERPRET},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        cache_key = profile_list_search_cache_key(
            kind="search",
            filters_json=canonical_filters(flt),
            page=page,
            limit=limit,
            sort_by=sort_by,
            order=order,
        )
        hit = cache.get(cache_key)
        if hit is not None:
            return Response(hit, status=status.HTTP_200_OK)

        qs = Profile.objects.all()
        qs = apply_filters(qs, flt)
        total = qs.count()
        qs = apply_sort(qs, sort_by, order)
        start = (page - 1) * limit
        rows = list(qs[start : start + limit])
        links = build_pagination_links(
            path=SEARCH_PATH,
            query_params=request.query_params,
            param_keys=ALLOWED_SEARCH_PARAMS,
            page=page,
            limit=limit,
            total=total,
        )
        payload = {
            "status": "success",
            "page": int(page),
            "limit": int(limit),
            "total": int(total),
            "total_pages": int(total_pages_count(total, limit)),
            "links": links,
            "data": [_full_profile_dict(p) for p in rows],
        }
        cache.set(cache_key, payload, timeout=LIST_SEARCH_CACHE_TIMEOUT)
        return Response(
            payload,
            status=status.HTTP_200_OK,
        )


class ProfileDetailView(APIView):
    """GET one profile by UUID, or DELETE it (admin); delete invalidates list/search cache."""

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [
                IsActiveInsightaUser(),
                IsInsightaAdmin(),
            ]
        return [IsActiveInsightaUser()]

    def get(self, request: Request, profile_id: str) -> Response:
        """Resolve UUID pk and return `{ status, data }` or generic 404 if missing."""
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
        """Hard-delete row and bump cached list generations so deletes become visible."""
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
        bump_profile_query_cache_generation()
        return Response(status=status.HTTP_204_NO_CONTENT)
