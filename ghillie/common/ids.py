"""Identifier helpers shared by storage models."""

from __future__ import annotations

import uuid


def new_uuid7_str() -> str:
    """Return a canonical UUIDv7 string for storage primary keys."""
    return str(uuid.uuid7())
