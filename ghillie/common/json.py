"""Shared type aliases for dynamic JSON-like payloads.

These aliases intentionally stay lightweight. External payloads often start as
loosely validated dictionaries and are narrowed incrementally by callers.
"""

from __future__ import annotations

import typing as typ

type JSONLike = dict[str, typ.Any]
type JSONValue = JSONLike | list[typ.Any] | str | int | float | bool | None
