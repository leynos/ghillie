"""Common time utilities."""

from __future__ import annotations

import datetime as dt


def utcnow() -> dt.datetime:
    """Return an aware UTC timestamp suitable for DB defaults."""
    return dt.datetime.now(dt.UTC)
