"""Identifier helpers shared by storage models.

These helpers centralize identifier generation policies used by SQLAlchemy
storage models across the catalogue, Silver, and Gold layers. Use this module
when a storage-facing primary key or persisted identifier needs to be generated
in a consistent format without duplicating UUID policy in each model.

Functions in this module return canonical UUID strings so existing
``String(36)`` database columns and external payload shapes remain unchanged
while the generation strategy can evolve in one place.

Examples
--------
Generate a new storage identifier:

>>> from ghillie.common.ids import new_uuid7_str
>>> identifier = new_uuid7_str()
>>> len(identifier)
36

"""

from __future__ import annotations

import uuid


def new_uuid7_str() -> str:
    """Return a canonical UUIDv7 string for storage primary keys.

    Returns
    -------
    str
        Canonical UUIDv7 text in the standard 36-character hyphenated format.

    Examples
    --------
    >>> from ghillie.common.ids import new_uuid7_str
    >>> value = new_uuid7_str()
    >>> value.count("-")
    4

    """
    return str(uuid.uuid7())
