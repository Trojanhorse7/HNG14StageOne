"""UUID v7 generation (stdlib adds uuid7 in Python 3.13+)."""

from __future__ import annotations

import sys
import uuid

if sys.version_info >= (3, 13):
    def new_uuid7() -> uuid.UUID:
        return uuid.uuid7()  # type: ignore[attr-defined]
else:
    from uuid6 import uuid7

    def new_uuid7() -> uuid.UUID:
        return uuid7()
