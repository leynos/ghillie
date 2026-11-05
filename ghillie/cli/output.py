"""Output formatting helpers for the operator CLI.

JSON and YAML success output is the server document unchanged and is a
contract (D7); table output is for humans and may change. Errors use the
``{"error": ...}`` envelope in machine-readable modes and labelled lines in
table mode.
"""

from __future__ import annotations

import collections.abc as cabc
import io
import json
import typing as typ

from ruamel.yaml import YAML

if typ.TYPE_CHECKING:
    from .config import OutputFormat
    from .control_plane import ControlPlaneError

Column = tuple[str, str]
"""A table column: dotted field path and heading."""


def render_output(payload: typ.Mapping[str, object], *, output: OutputFormat) -> str:
    """Render one CLI payload according to the selected output format."""
    if output == "json":
        return json.dumps(payload, sort_keys=True)
    if output == "yaml":
        return _dump_yaml(dict(payload))
    return "\n".join(f"{key}: {value}" for key, value in payload.items())


def render_collection(
    items: typ.Iterable[typ.Mapping[str, object]],
    *,
    columns: typ.Sequence[Column],
    output: OutputFormat,
    meta: typ.Mapping[str, object],
) -> str:
    """Render a paginated collection.

    ``json`` and ``yaml`` keep the whole server document (D7), including the
    pagination metadata. ``table`` shows the requested columns and the
    metadata as a trailing line so an operator can walk the next page.
    """
    rows = [dict(item) for item in items]
    if output == "json":
        return json.dumps({**meta, "items": rows}, sort_keys=True)
    if output == "yaml":
        return _dump_yaml({**meta, "items": rows})
    return _render_rows(rows, columns, meta)


def render_document(payload: typ.Mapping[str, object], *, output: OutputFormat) -> str:
    """Render one successful operation document.

    ``json`` and ``yaml`` return the server document unchanged; ``table``
    flattens nested mappings into dotted keys so counts stay readable.
    """
    if output == "json":
        return json.dumps(payload, sort_keys=True)
    if output == "yaml":
        return _dump_yaml(dict(payload))
    return "\n".join(
        f"{name}: {_format_value(value)}" for name, value in _flatten(dict(payload))
    )


def render_error(error: ControlPlaneError, *, output: OutputFormat) -> str:
    """Render one failure in the selected output format.

    The hint is expected to be populated by the command layer; the envelope
    omits ``status`` for local failures and ``issues`` when there are none.
    """
    document = {"error": _error_fields(error)}
    if output == "json":
        return json.dumps(document, sort_keys=True)
    if output == "yaml":
        return _dump_yaml(document)

    lines = [f"Error: {error.message}", f"Code: {error.code}"]
    if error.status is not None:
        lines.append(f"Status: {error.status}")
    if error.hint:
        lines.append(f"Hint: {error.hint}")
    lines.extend(f"Issue: {issue.code}: {issue.message}" for issue in error.issues)
    return "\n".join(lines)


def _error_fields(error: ControlPlaneError) -> dict[str, object]:
    """Build the documented error body, omitting absent optional fields."""
    fields: dict[str, object] = {"code": error.code, "message": error.message}
    if error.hint:
        fields["hint"] = error.hint
    if error.status is not None:
        fields["status"] = error.status
    if error.issues:
        fields["issues"] = [
            {"code": issue.code, "message": issue.message} for issue in error.issues
        ]
    return fields


def _dump_yaml(payload: object) -> str:
    """Dump *payload* as block-style YAML without a document marker."""
    buffer = io.StringIO()
    yaml = YAML(typ="safe")
    yaml.default_flow_style = False
    yaml.dump(payload, buffer)
    return buffer.getvalue().strip()


def _flatten(
    payload: cabc.Mapping[str, object],
    prefix: str = "",
) -> typ.Iterator[tuple[str, object]]:
    """Yield dotted field names, recursing into nested mappings."""
    for key, value in payload.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, cabc.Mapping):
            yield from _flatten(typ.cast("cabc.Mapping[str, object]", value), name)
        else:
            yield name, value


def _lookup(item: cabc.Mapping[str, object], field: str) -> object:
    """Read a possibly dotted *field* from one row."""
    value: object = item
    for part in field.split("."):
        if not isinstance(value, cabc.Mapping):
            return None
        value = value.get(part)
    return value


def _format_value(value: object) -> str:
    """Format one document value for table output."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _format_meta_value(value: object) -> str:
    """Format a pagination value, spelling ``None`` the way JSON does."""
    if value is None:
        return "null"
    return _format_value(value)


def _render_rows(
    rows: list[dict[str, object]],
    columns: typ.Sequence[Column],
    meta: typ.Mapping[str, object],
) -> str:
    """Render an aligned table plus a pagination line."""
    headings = [heading for _, heading in columns]
    cells = [
        [_format_value(_lookup(row, field)) for field, _ in columns] for row in rows
    ]
    widths = [
        max(len(heading), *(len(cell[index]) for cell in cells))
        if cells
        else len(heading)
        for index, heading in enumerate(headings)
    ]
    lines = [
        "  ".join(
            heading.ljust(width)
            for heading, width in zip(headings, widths, strict=True)
        ).rstrip()
    ]
    if cells:
        lines.extend(
            "  ".join(
                value.ljust(width) for value, width in zip(row, widths, strict=True)
            ).rstrip()
            for row in cells
        )
    else:
        lines.append("(no items)")
    if meta:
        lines.append("")
        lines.append(
            " ".join(
                f"{key}={_format_meta_value(value)}" for key, value in meta.items()
            )
        )
    return "\n".join(lines)
