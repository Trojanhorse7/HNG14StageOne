"""Shared parsing/validation for `/api/profiles` query strings and queryset composition.

Unknown query keys raise `ValueError` so views can map them to HTTP 422 payloads.
"""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from classify.models import Profile

ALLOWED_LIST_PARAMS = frozenset(
    {
        "gender",
        "age_group",
        "country_id",
        "min_age",
        "max_age",
        "min_gender_probability",
        "min_country_probability",
        "sort_by",
        "order",
        "page",
        "limit",
        # `format` conflicts with DRF content negotiation — export uses export_format only.
        "export_format",
    }
)

ALLOWED_SEARCH_PARAMS = frozenset({"q", "page", "limit"})

SORT_FIELDS = frozenset({"age", "created_at", "gender_probability"})

ERR_INVALID_QUERY = "Invalid query parameters"
ERR_BAD_REQUEST = "Missing or empty parameter"


def _get_first(query_dict: Any, key: str) -> str | None:
    """Best-effort scalar read (DRF may hand list/tuple values for repeated keys)."""
    v = query_dict.get(key)
    if v is None:
        return None
    if isinstance(v, (list, tuple)) and v:
        v = v[0]
    s = str(v).strip()
    return s if s else None


def parse_list_query_params(query_dict: Any) -> dict[str, Any]:
    """Validate/normalize list filters, sort, pagination; max `limit` capped at 50."""
    for k in query_dict.keys():
        if k not in ALLOWED_LIST_PARAMS:
            raise ValueError(ERR_INVALID_QUERY)

    out: dict[str, Any] = {}
    g = _get_first(query_dict, "gender")
    if g is not None:
        out["gender"] = g.lower()
    ag = _get_first(query_dict, "age_group")
    if ag is not None:
        out["age_group"] = ag.lower()
    c = _get_first(query_dict, "country_id")
    if c is not None:
        t = c.strip()
        if not t or len(t) < 2:
            raise ValueError(ERR_INVALID_QUERY)
        out["country_id"] = t[:2].upper()
    for key in ("min_age", "max_age"):
        s = _get_first(query_dict, key)
        if s is not None:
            try:
                out[key] = int(s)
            except (TypeError, ValueError) as e:
                raise ValueError(ERR_INVALID_QUERY) from e
    for key in ("min_gender_probability", "min_country_probability"):
        s = _get_first(query_dict, key)
        if s is not None:
            try:
                out[key] = float(s)
            except (TypeError, ValueError) as e:
                raise ValueError(ERR_INVALID_QUERY) from e
    sby = _get_first(query_dict, "sort_by")
    if sby is not None:
        if sby not in SORT_FIELDS:
            raise ValueError(ERR_INVALID_QUERY)
        out["sort_by"] = sby
    o = _get_first(query_dict, "order")
    if o is not None:
        ol = o.lower()
        if ol not in ("asc", "desc"):
            raise ValueError(ERR_INVALID_QUERY)
        out["order"] = ol
    page = _get_first(query_dict, "page")
    if page is not None:
        try:
            p = int(page)
            if p < 1:
                raise ValueError
            out["page"] = p
        except (TypeError, ValueError) as e:
            raise ValueError(ERR_INVALID_QUERY) from e
    lim = _get_first(query_dict, "limit")
    if lim is not None:
        try:
            l = int(lim)
            if l < 1:
                raise ValueError
            out["limit"] = min(l, 50)
        except (TypeError, ValueError) as e:
            raise ValueError(ERR_INVALID_QUERY) from e
    return out


def parse_search_query_params(query_dict: Any) -> dict[str, Any]:
    """Accept only `q`, `page`, `limit` for `/api/profiles/search`."""
    for k in query_dict.keys():
        if k not in ALLOWED_SEARCH_PARAMS:
            raise ValueError(ERR_INVALID_QUERY)
    out: dict[str, Any] = {}
    q = _get_first(query_dict, "q")
    if q is not None:
        out["q"] = q
    page = _get_first(query_dict, "page")
    if page is not None:
        try:
            p = int(page)
            if p < 1:
                raise ValueError
            out["page"] = p
        except (TypeError, ValueError) as e:
            raise ValueError(ERR_INVALID_QUERY) from e
    lim = _get_first(query_dict, "limit")
    if lim is not None:
        try:
            l = int(lim)
            if l < 1:
                raise ValueError
            out["limit"] = min(l, 50)
        except (TypeError, ValueError) as e:
            raise ValueError(ERR_INVALID_QUERY) from e
    return out


def apply_filters(
    qs: QuerySet[Profile], filters: dict[str, Any]
) -> QuerySet[Profile]:
    """AND-combine structured filters understood by NL + classic list endpoints."""
    g = filters.get("gender")
    if g is not None:
        qs = qs.filter(gender__iexact=str(g))
    ag = filters.get("age_group")
    if ag is not None:
        qs = qs.filter(age_group__iexact=str(ag))
    cid = filters.get("country_id")
    if cid is not None:
        qs = qs.filter(country_id__iexact=str(cid)[:2])
    ma = filters.get("min_age")
    if ma is not None:
        qs = qs.filter(age__gte=int(ma))
    xa = filters.get("max_age")
    if xa is not None:
        qs = qs.filter(age__lte=int(xa))
    mg = filters.get("min_gender_probability")
    if mg is not None:
        qs = qs.filter(gender_probability__gte=float(mg))
    mc = filters.get("min_country_probability")
    if mc is not None:
        qs = qs.filter(country_probability__gte=float(mc))
    return qs


def apply_sort(qs: QuerySet[Profile], sort_by: str, order: str) -> QuerySet[Profile]:
    """Deterministic ordering: primary field (`sort_by`) plus matching `id` tie-break."""

    if sort_by == "age":
        f = "age"
    elif sort_by == "created_at":
        f = "created_at"
    else:
        f = "gender_probability"
    pfx = "" if order == "asc" else "-"
    return qs.order_by(f"{pfx}{f}", f"{pfx}id")
