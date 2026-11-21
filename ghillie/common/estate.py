"""Estate constants shared by the domain, the HTTP adapter and the CLI.

These values are part of the contract an operator and the service both depend
on: the pattern a new estate key must match, and the largest page offset any
listing accepts. They live here rather than in :mod:`ghillie.estate.models`
because importing anything under :mod:`ghillie.estate` loads that package's
application re-exports, which the CLI must not pull in (O6). Keeping one
dependency-free definition lets the CLI, the application service, and the HTTP
adapter agree without either copying the value or importing the server side.

The module imports nothing, so it sits in the ``domain_ports`` Hecate group and
stays safe for every layer to import.
"""

from __future__ import annotations

MAX_PAGE_OFFSET = 2**31 - 1
"""Largest offset any estate listing accepts.

A signed 32-bit ceiling is far beyond any real estate listing and stays within
the native integer range of every store the project supports. The persistence
adapter enforces the same bound before it binds the value, so an offset that
reaches it despite this check is rejected as invalid pagination rather than
failing in the driver.
"""

NEW_ESTATE_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
"""Pattern a *new* estate key must match.

Other endpoints accept any key of the documented maximum length so that keys
created earlier through Python remain reachable.
"""
