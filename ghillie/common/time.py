"""Common time utilities."""

import datetime as dt


def utcnow() -> dt.datetime:
    """Return an aware UTC timestamp suitable for DB defaults."""
    return dt.datetime.now(dt.UTC)
