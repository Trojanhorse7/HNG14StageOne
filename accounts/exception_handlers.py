"""Map DRF/validation exceptions into `{ "status": "error", "message": str }` bodies."""


from __future__ import annotations

from typing import Any

from rest_framework.views import exception_handler


def _message_from_data(data: Any) -> str:
    if data is None:
        return "Request failed"
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        if "detail" in data:
            d = data["detail"]
            if isinstance(d, list) and d:
                return str(d[0])
            return str(d)
        for v in data.values():
            if isinstance(v, list) and v:
                return str(v[0])
            if v is not None:
                return str(v)
        return "Invalid request"
    if isinstance(data, list) and data:
        return str(data[0])
    return str(data)


def insighta_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response
    msg = _message_from_data(response.data)
    response.data = {"status": "error", "message": msg}
    return response
