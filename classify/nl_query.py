"""NL to profile filter kwargs via regex rules (no ML).
Normalized text + word boundaries reduce false country/gender matches."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from classify.country_data import COUNTRY_ID_TO_NAME


def _strip_accents(s: str) -> str:
    """Strip combining marks so "Côte" matches the same letters as "cote"."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _norm(s: str) -> str:
    """Lowercase, de-accent, squash punctuation to spaces for robust token matching."""
    s = (s or "").lower().strip()
    s = _strip_accents(s)
    s = s.replace("'", " ").replace("’", " ")
    s = re.sub(r"[^\w\d]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _country_id_from_text(norm_q: str) -> str | None:
    """Detect ISO2 by longest country name match first to avoid Niger vs Nigeria clashes."""
    if not norm_q:
        return None
    items = list(COUNTRY_ID_TO_NAME.items())
    items.sort(key=lambda kv: len(_norm(kv[1])), reverse=True)
    for cid, cname in items:
        words = [w for w in _norm(cname).split() if w]
        if not words:
            continue
        if len(words) == 1:
            pat = rf"(?<!\w){re.escape(words[0])}(?!\w)"
        else:
            # Build regex outside f-string: PEP 498 disallows backslashes inside `{...}`.
            middle = r"\W+".join(re.escape(w) for w in words)
            pat = rf"(?<!\w){middle}(?!\w)"
        if re.search(pat, norm_q, flags=re.IGNORECASE):
            return cid
    return None


_YOUNG_MIN, _YOUNG_MAX = 16, 24

_BOTH_PATTERN = re.compile(
    r"(?P<a>males?|men|man)\s+and\s+(?P<b>females?|women|woman)"
    r"|"
    r"(?P<a2>females?|women|woman)\s+and\s+(?P<b2>males?|men|man)",
    re.IGNORECASE,
)


def _merge_age(
    lo: int | None, hi: int | None, new_lo: int | None, new_hi: int | None
) -> tuple[int | None, int | None] | None:
    """Intersect interpreted age bounds; return None if constraints contradict."""
    l = new_lo if new_lo is not None else lo
    h = new_hi if new_hi is not None else hi
    if lo is not None and new_lo is not None:
        l = max(lo, new_lo)
    elif new_lo is not None:
        l = new_lo
    elif lo is not None:
        l = lo
    if hi is not None and new_hi is not None:
        h = min(hi, new_hi)
    elif new_hi is not None:
        h = new_hi
    elif hi is not None:
        h = hi
    if l is not None and h is not None and l > h:
        return None
    return l, h


def parse_nl_query(q: str) -> dict[str, Any] | None:
    """Map free text to `apply_filters` kwargs, or None when no safe interpretation exists."""
    if not (q and q.strip()):
        return None

    raw = q.strip()
    nq = _norm(raw)
    if not nq:
        return None

    filters: dict[str, Any] = {}
    min_age: int | None = None
    max_age: int | None = None

    # Strip polite/filler tokens from `work`; country detection still scans full `nq` as well.
    work = nq
    for filler in (
        "people",
        "persons",
        "person",
        "show me",
        "find",
        "all",
        "from",
        "in",
    ):
        work = re.sub(rf"(?<!\w){filler}(?!\w)", " ", work)
    work = re.sub(r"\s+", " ", work).strip()

    country = _country_id_from_text(nq) or _country_id_from_text(work)
    if country:
        filters["country_id"] = country

    both = _BOTH_PATTERN.search(work)
    if both:
        work = work[: both.start()] + " " + work[both.end() :]
        work = re.sub(r"\s+", " ", work).strip()
    else:
        has_m = bool(
            re.search(
                r"(?<![a-zA-Z])(?:males?|men|man)(?![a-zA-Z])", work, re.IGNORECASE
            )
        )
        has_f = bool(
            re.search(
                r"(?<![a-zA-Z])(?:females?|women|woman)(?![a-zA-Z])", work, re.IGNORECASE
            )
        )
        if has_m and has_f:
            pass
        elif has_m:
            filters["gender"] = "male"
        elif has_f:
            filters["gender"] = "female"

    for word, group in (
        ("child", "child"),
        ("children", "child"),
        ("teenager", "teenager"),
        ("teenagers", "teenager"),
        ("adult", "adult"),
        ("adults", "adult"),
        ("senior", "senior"),
        ("seniors", "senior"),
        ("elderly", "senior"),
    ):
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", work):
            if "age_group" in filters and filters["age_group"] != group:
                return None
            filters["age_group"] = group

    if re.search(r"(?<!\w)young(?!\w)", work):
        m = _merge_age(min_age, max_age, _YOUNG_MIN, _YOUNG_MAX)
        if m is None:
            return None
        min_age, max_age = m

    for m in re.finditer(
        r"(?:(?:above|over|older\s+than)\s*(?P<am>\d+)|(?P<as>\d+)\s*\+|(?:at\s*least)\s*(?P<al>\d+))",
        work,
    ):
        n = m.group("am") or m.group("al") or m.group("as")
        if n is None:
            continue
        v = int(n)
        merged = _merge_age(min_age, max_age, v, None)
        if merged is None:
            return None
        min_age, max_age = merged

    for m in re.finditer(
        r"(?:(?:below|under|younger\s+than)\s*(?P<u>\d+)|(?:at\s*most)\s*(?P<am2>\d+))",
        work,
    ):
        n = m.group("u") or m.group("am2")
        if n is None:
            continue
        v = int(n) - 1
        if v < 0:
            v = 0
        merged = _merge_age(min_age, max_age, None, v)
        if merged is None:
            return None
        min_age, max_age = merged

    if min_age is not None:
        filters["min_age"] = min_age
    if max_age is not None:
        filters["max_age"] = max_age

    if not filters:
        return None

    return filters
