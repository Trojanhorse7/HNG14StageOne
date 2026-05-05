"""Profile list/search cache helpers: stable filter JSON, versioned keys, generation bump.

Queries differ when data changes, so keys embed a monotonic generation counter updated on writes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.core.cache import cache

PROFILE_QUERY_CACHE_GEN_KEY = "profile_query_cache_gen"


def get_profile_query_cache_generation() -> int:
    """Read the current invalidation generation from cache (defaults to 0 if unset)."""
    v = cache.get(PROFILE_QUERY_CACHE_GEN_KEY)
    if isinstance(v, int):
        return v
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def bump_profile_query_cache_generation() -> None:
    """Increment generation so all profile list/search cache keys miss after mutations."""
    try:
        cache.incr(PROFILE_QUERY_CACHE_GEN_KEY)
    except ValueError:
        cache.set(PROFILE_QUERY_CACHE_GEN_KEY, 1, timeout=None)


def canonical_filters(filters: dict[str, Any]) -> str:
    """Stable minified JSON: sorted keys and normalized values so equivalent filters collide in cache."""
    out: dict[str, Any] = {}
    if "gender" in filters:
        out["gender"] = str(filters["gender"]).strip().lower()
    if "age_group" in filters:
        out["age_group"] = str(filters["age_group"]).strip().lower()
    if "country_id" in filters:
        cid = str(filters["country_id"]).strip().upper()[:2]
        out["country_id"] = cid
    if "min_age" in filters:
        out["min_age"] = int(filters["min_age"])
    if "max_age" in filters:
        out["max_age"] = int(filters["max_age"])
    if "min_gender_probability" in filters:
        out["min_gender_probability"] = round(float(filters["min_gender_probability"]), 6)
    if "min_country_probability" in filters:
        out["min_country_probability"] = round(float(filters["min_country_probability"]), 6)
    return json.dumps(out, sort_keys=True, separators=(",", ":"))


def profile_list_search_cache_key(
    *,
    kind: str,
    filters_json: str,
    page: int,
    limit: int,
    sort_by: str,
    order: str,
) -> str:
    """SHA-256 over kind (list vs search), filters, paging, sort order, and cache generation."""
    gen = get_profile_query_cache_generation()
    raw = f"v1:{kind}:{filters_json}:p={page}:l={limit}:s={sort_by}:o={order}:g={gen}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"profile_q:{digest}"

