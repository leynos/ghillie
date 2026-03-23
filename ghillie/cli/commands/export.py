"""Export noun commands for the packaged operator CLI."""

from __future__ import annotations

import typing as typ
from pathlib import Path

from cyclopts import App, Parameter

from ghillie.cli.commands.params import (
    ExportFormat,
    ExportSinkOptions,
    ResourceScope,
    ResourceTarget,
    WindowOptions,
)
from ghillie.cli.context import get_current_context
from ghillie.cli.control_plane import ControlPlaneClient
from ghillie.cli.output import render_output

export_app = App(name="export", help="Export structured MVP data artefacts.")


def _api_placeholder(verb: str, **fields: object) -> str:
    context = get_current_context()
    with ControlPlaneClient(context.config):
        return render_output(
            {
                "noun": "export",
                "verb": verb,
                "status": "not_implemented",
                "message": "not implemented in Task 2.5.a",
                **fields,
            },
            output=context.config.output,
        )


def _export_command(  # noqa: PLR0913
    kind: str,
    *,
    target: ResourceTarget,
    window: WindowOptions,
    sink: ExportSinkOptions,
    extra_fields: typ.Mapping[str, object] | None = None,
) -> str:
    return _api_placeholder(
        kind,
        scope=target.scope,
        estate_key=target.estate_key or "",
        owner=target.owner or "",
        name=target.name or "",
        window_days=window.window_days if window.window_days is not None else "",
        window_start=window.window_start or "",
        window_end=window.window_end or "",
        format=sink.export_format,
        output_path=str(sink.output_path),
        **(extra_fields or {}),
    )


@export_app.command
def events(
    *,
    target: ResourceTarget,
    window: WindowOptions | None = None,
    sink: ExportSinkOptions | None = None,
) -> str:
    """Export Bronze and Silver event data."""
    if window is None:
        window = WindowOptions()
    if sink is None:
        sink = ExportSinkOptions()
    return _export_command("events", target=target, window=window, sink=sink)


# @codescene(disable:"Excess Number of Function Arguments")
# 2026-03-22: CLI command entry point keeps explicit options for operator UX.
@export_app.command
def evidence(  # noqa: PLR0913
    *,
    scope: ResourceScope,
    estate_key: str | None = None,
    owner: str | None = None,
    name: str | None = None,
    window_days: int | None = 14,
    window_start: str | None = None,
    window_end: str | None = None,
    export_format: typ.Annotated[ExportFormat, Parameter(name="--format")] = (
        ExportFormat.JSON
    ),
    output_path: str,
    include_previous_reports: bool = False,
) -> str:
    """Export derived evidence bundles."""
    target = ResourceTarget(scope=scope, estate_key=estate_key, owner=owner, name=name)
    window = WindowOptions(
        window_days=window_days, window_start=window_start, window_end=window_end
    )
    sink = ExportSinkOptions(export_format=export_format, output_path=Path(output_path))
    return _export_command(
        "evidence",
        target=target,
        window=window,
        sink=sink,
        extra_fields={"include_previous_reports": include_previous_reports},
    )


# @codescene(disable:"Excess Number of Function Arguments")
# 2026-03-22: CLI command entry point keeps explicit options for operator UX.
@export_app.command
def reports(  # noqa: PLR0913
    *,
    scope: ResourceScope,
    estate_key: str | None = None,
    owner: str | None = None,
    name: str | None = None,
    window_days: int | None = 14,
    window_start: str | None = None,
    window_end: str | None = None,
    export_format: typ.Annotated[ExportFormat, Parameter(name="--format")] = (
        ExportFormat.JSON
    ),
    output_path: str,
    include_coverage: bool = False,
) -> str:
    """Export report metadata and lineage."""
    target = ResourceTarget(scope=scope, estate_key=estate_key, owner=owner, name=name)
    window = WindowOptions(
        window_days=window_days, window_start=window_start, window_end=window_end
    )
    sink = ExportSinkOptions(export_format=export_format, output_path=Path(output_path))
    return _export_command(
        "reports",
        target=target,
        window=window,
        sink=sink,
        extra_fields={"include_coverage": include_coverage},
    )


# @codescene(disable:"Excess Number of Function Arguments")
# 2026-03-22: CLI command entry point keeps explicit options for operator UX.
@export_app.command
def bundle(  # noqa: PLR0913
    *,
    scope: ResourceScope,
    estate_key: str | None = None,
    owner: str | None = None,
    name: str | None = None,
    window_days: int = 14,
    export_format: typ.Annotated[
        typ.Literal[ExportFormat.JSON], Parameter(name="--format")
    ] = ExportFormat.JSON,
    output_path: str,
) -> str:
    """Export a combined bundle artefact."""
    target = ResourceTarget(scope=scope, estate_key=estate_key, owner=owner, name=name)
    sink = ExportSinkOptions(export_format=export_format, output_path=Path(output_path))
    return _api_placeholder(
        "bundle",
        scope=target.scope,
        estate_key=target.estate_key or "",
        owner=target.owner or "",
        name=target.name or "",
        window_days=window_days,
        format=sink.export_format,
        output_path=str(sink.output_path),
    )
