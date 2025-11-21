"""JSON Schema generation for the estate catalogue."""

from __future__ import annotations

import json
import typing as typ
from pathlib import Path  # noqa: TC003

import msgspec

from .models import Catalogue

SCHEMA_ID = "https://ghillie.example/schemas/catalogue.json"


def build_catalogue_schema() -> dict[str, typ.Any]:
    """Build the JSON Schema for catalogue data structures.

    Returns
    -------
    dict[str, Any]
        JSON Schema describing the catalogue, with ``$id`` set to
        ``SCHEMA_ID``.

    """
    schema = msgspec.json.schema(Catalogue)
    schema["$id"] = SCHEMA_ID
    return schema


def write_catalogue_schema(path: Path) -> Path:
    """Persist the generated JSON Schema to disk, creating parent directories.

    Parameters
    ----------
    path : Path
        Destination path for the schema JSON file.

    Returns
    -------
    Path
        The path written to, for convenience in call chains.

    """
    schema = build_catalogue_schema()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return path
