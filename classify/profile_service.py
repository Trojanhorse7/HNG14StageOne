"""Fetch and validate Genderize, Agify, and Nationalize payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from classify.country_data import country_name_for_id

GENDERIZE_URL = "https://api.genderize.io/"
AGIFY_URL = "https://api.agify.io/"
NATIONALIZE_URL = "https://api.nationalize.io/"


@dataclass(frozen=True)
class AggregatedProfile:
    gender: str
    gender_probability: float
    age: int
    age_group: str
    country_id: str
    country_name: str
    country_probability: float


def _age_group(age: int) -> str:
    if age <= 12:
        return "child"
    if age <= 19:
        return "teenager"
    if age <= 59:
        return "adult"
    return "senior"


def _invalid_response_error(external_api: str) -> dict[str, str]:
    return {
        "status": "502",
        "message": f"{external_api} returned an invalid response",
    }


def _fetch_json(url: str, params: dict[str, str], external_api: str):
    try:
        resp = requests.get(url, params=params, timeout=15)
    except requests.RequestException:
        return None, _invalid_response_error(external_api)
    if not resp.ok:
        return None, _invalid_response_error(external_api)
    try:
        return resp.json(), None
    except ValueError:
        return None, _invalid_response_error(external_api)


def aggregate_for_name(name: str) -> tuple[AggregatedProfile | None, dict[str, str] | None]:
    """Return aggregated data or an error dict for JSON response body (HTTP 502)."""

    g_payload, err = _fetch_json(GENDERIZE_URL, {"name": name}, "Genderize")
    if err:
        return None, err

    gender = g_payload.get("gender")
    g_count = g_payload.get("count")
    g_prob = g_payload.get("probability")
    if gender is None or g_count == 0:
        return None, _invalid_response_error("Genderize")
    try:
        gender_probability = float(g_prob)
        int(g_count)  # validate
    except (TypeError, ValueError):
        return None, _invalid_response_error("Genderize")

    a_payload, err = _fetch_json(AGIFY_URL, {"name": name}, "Agify")
    if err:
        return None, err
    age = a_payload.get("age")
    if age is None:
        return None, _invalid_response_error("Agify")
    try:
        age_i = int(age)
    except (TypeError, ValueError):
        return None, _invalid_response_error("Agify")

    n_payload, err = _fetch_json(NATIONALIZE_URL, {"name": name}, "Nationalize")
    if err:
        return None, err
    countries = n_payload.get("country")
    if not countries or not isinstance(countries, list):
        return None, _invalid_response_error("Nationalize")

    best: dict[str, Any] | None = None
    best_p = -1.0
    for item in countries:
        if not isinstance(item, dict):
            continue
        cid = item.get("country_id")
        prob = item.get("probability")
        if cid is None or prob is None:
            continue
        try:
            pf = float(prob)
        except (TypeError, ValueError):
            continue
        if pf > best_p:
            best_p = pf
            best = item

    if best is None or best_p < 0:
        return None, _invalid_response_error("Nationalize")

    country_id = str(best["country_id"]).upper()
    gender_s = str(gender).lower()
    cname = country_name_for_id(country_id)
    if cname is None:
        cname = country_id

    return (
        AggregatedProfile(
            gender=gender_s,
            gender_probability=gender_probability,
            age=age_i,
            age_group=_age_group(age_i),
            country_id=country_id,
            country_name=cname,
            country_probability=best_p,
        ),
        None,
    )
