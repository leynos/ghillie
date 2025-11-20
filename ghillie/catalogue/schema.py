"""JSON Schema generation for the estate catalogue."""

from __future__ import annotations

import json
import typing as typ

import msgspec

if typ.TYPE_CHECKING:
    from pathlib import Path

from .models import Catalogue

SCHEMA_ID = "https://ghillie.example/schemas/catalogue.json"


def build_catalogue_schema() -> dict[str, typ.Any]:
    """Return the JSON Schema describing the catalogue structures."""
    schema = msgspec.json.schema(Catalogue)
    schema.setdefault("$id", SCHEMA_ID)
    return schema


def write_catalogue_schema(path: Path) -> Path:
    """Persist the generated JSON Schema to disk, creating parents."""
    schema = build_catalogue_schema()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return path
