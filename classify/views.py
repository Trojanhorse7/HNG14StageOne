"""GET /api/classify — Genderize.io integration."""

from datetime import datetime, timezone

import requests
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

GENDERIZE_URL = "https://api.genderize.io/"

ERR_NO_PREDICTION = "No prediction available for the provided name"
ERR_MISSING_NAME = "Missing or empty name parameter"
ERR_NAME_NOT_STRING = "name is not a string"


def _utc_iso8601_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ClassifyNameView(APIView):
    """Classify a given name using the Genderize API."""

    def get(self, request: Request) -> Response:
        name_values = request.GET.getlist("name")

        if len(name_values) > 1:
            return Response(
                {"status": "error", "message": ERR_NAME_NOT_STRING},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        if "name" not in request.GET:
            return Response(
                {"status": "error", "message": ERR_MISSING_NAME},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw = name_values[0] if name_values else request.GET.get("name", "")
        if not isinstance(raw, str):
            return Response(
                {"status": "error", "message": ERR_NAME_NOT_STRING},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        name = raw.strip()
        if not name:
            return Response(
                {"status": "error", "message": ERR_MISSING_NAME},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            upstream = requests.get(
                GENDERIZE_URL,
                params={"name": name},
                timeout=10,
            )
        except requests.RequestException:
            return Response(
                {"status": "error", "message": "Upstream service unavailable"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not upstream.ok:
            return Response(
                {"status": "error", "message": "Upstream service returned an error"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            payload = upstream.json()
        except ValueError:
            return Response(
                {"status": "error", "message": "Invalid response from upstream service"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        gender = payload.get("gender")
        probability = payload.get("probability")
        sample_size = payload.get("count")

        if gender is None or sample_size == 0:
            return Response(
                {"status": "error", "message": ERR_NO_PREDICTION},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        try:
            prob_f = float(probability)
            size_i = int(sample_size)
        except (TypeError, ValueError):
            return Response(
                {"status": "error", "message": ERR_NO_PREDICTION},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        is_confident = prob_f >= 0.7 and size_i >= 100

        return Response(
            {
                "status": "success",
                "data": {
                    "name": name,
                    "gender": gender,
                    "probability": prob_f,
                    "sample_size": size_i,
                    "is_confident": is_confident,
                    "processed_at": _utc_iso8601_z(),
                },
            },
            status=status.HTTP_200_OK,
        )
