"""UUIDv7 primary keys: use stdlib on Python 3.13+, else backport via `uuid6`."""

from __future__ import annotations

import sys
import uuid

if sys.version_info >= (3, 13):

    def new_uuid7() -> uuid.UUID:
        """Return time-sortable UUID for database-friendly clustered inserts."""
        return uuid.uuid7()  # type: ignore[attr-defined]
else:
    from uuid6 import uuid7

    def new_uuid7() -> uuid.UUID:
        """Return time-sortable UUID for database-friendly clustered inserts."""
        return uuid7()
