"""TRD pagination links (relative paths + query string)."""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlencode


def total_pages_count(total: int, limit: int) -> int:
    if limit < 1 or total < 1:
        return 0
    return math.ceil(total / limit)


def build_pagination_links(
    *,
    path: str,
    query_params: Any,
    param_keys: frozenset[str],
    page: int,
    limit: int,
    total: int,
) -> dict[str, str | None]:
    base: dict[str, str] = {}
    for key in sorted(param_keys):
        if key in ("page", "limit"):
            continue
        if key not in query_params:
            continue
        val = query_params.get(key)
        if val is not None and str(val) != "":
            base[key] = str(val)

    def link_for(p: int) -> str:
        params = {**base, "page": str(p), "limit": str(limit)}
        return f"{path}?{urlencode(params)}"

    total_pages = total_pages_count(total, limit)
    self_url = link_for(page)
    next_url: str | None = link_for(page + 1) if total_pages > 0 and page < total_pages else None
    prev_url: str | None = link_for(page - 1) if page > 1 else None
    return {"self": self_url, "next": next_url, "prev": prev_url}
