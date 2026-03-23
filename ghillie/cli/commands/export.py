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


def _flatten_target(target: ResourceTarget) -> dict[str, str]:
    """Flatten ResourceTarget fields for serialization."""
    return {
        "scope": target.scope,
        "estate_key": target.estate_key or "",
        "owner": target.owner or "",
        "name": target.name or "",
    }


def _flatten_sink(sink: ExportSinkOptions) -> dict[str, str]:
    """Flatten ExportSinkOptions fields for serialization."""
    return {
        "format": sink.export_format,
        "output_path": str(sink.output_path),
    }


def _export_command(
    kind: str,
    *,
    target: ResourceTarget,
    window: WindowOptions,
    sink: ExportSinkOptions,
    **extra_fields: object,
) -> str:
    return _api_placeholder(
        kind,
        **_flatten_target(target),
        window_days=window.window_days if window.window_days is not None else "",
        window_start=window.window_start or "",
        window_end=window.window_end or "",
        **_flatten_sink(sink),
        **extra_fields,
    )


@export_app.command
def events(
    *,
    target: ResourceTarget,
    window: WindowOptions | None = None,
    sink: ExportSinkOptions | None = None,
) -> str:
    """Export Bronze and Silver event data.

    Parameters
    ----------
    target : ResourceTarget
        Target resource specification (scope, estate_key, owner, name).
    window : WindowOptions | None, optional
        Time window for event selection (window_days, window_start, window_end).
        Defaults to WindowOptions() if None.
    sink : ExportSinkOptions | None, optional
        Export output configuration (export_format, output_path).
        Defaults to ExportSinkOptions() if None.

    Returns
    -------
    str
        JSON-serialized export status response from the control plane.

    """
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
    """Export derived evidence bundles.

    Parameters
    ----------
    scope : ResourceScope
        Target scope (estate, organization, or repository).
    estate_key : str | None, optional
        Estate identifier. Default is None.
    owner : str | None, optional
        Owner (organization or user) identifier. Default is None.
    name : str | None, optional
        Repository name. Default is None.
    window_days : int | None, optional
        Number of days to include in the export window. Default is 14.
    window_start : str | None, optional
        ISO 8601 start timestamp for the export window. Default is None.
    window_end : str | None, optional
        ISO 8601 end timestamp for the export window. Default is None.
    export_format : ExportFormat, optional
        Output format (JSON, CSV, etc.). Default is ExportFormat.JSON.
    output_path : str
        File path for the exported data.
    include_previous_reports : bool, optional
        Whether to include previous report metadata. Default is False.

    Returns
    -------
    str
        JSON-serialized export status response from the control plane.

    """
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
        include_previous_reports=include_previous_reports,
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
    """Export report metadata and lineage.

    Parameters
    ----------
    scope : ResourceScope
        Target scope (estate, organization, or repository).
    estate_key : str | None, optional
        Estate identifier. Default is None.
    owner : str | None, optional
        Owner (organization or user) identifier. Default is None.
    name : str | None, optional
        Repository name. Default is None.
    window_days : int | None, optional
        Number of days to include in the export window. Default is 14.
    window_start : str | None, optional
        ISO 8601 start timestamp for the export window. Default is None.
    window_end : str | None, optional
        ISO 8601 end timestamp for the export window. Default is None.
    export_format : ExportFormat, optional
        Output format (JSON, CSV, etc.). Default is ExportFormat.JSON.
    output_path : str
        File path for the exported data.
    include_coverage : bool, optional
        Whether to include coverage metrics in the export. Default is False.

    Returns
    -------
    str
        JSON-serialized export status response from the control plane.

    """
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
        include_coverage=include_coverage,
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
    export_format: typ.Annotated[ExportFormat, Parameter(name="--format")] = (
        ExportFormat.JSON
    ),
    output_path: str,
) -> str:
    """Export a combined bundle artefact.

    Parameters
    ----------
    scope : ResourceScope
        Target scope (estate, organization, or repository).
    estate_key : str | None, optional
        Estate identifier. Default is None.
    owner : str | None, optional
        Owner (organization or user) identifier. Default is None.
    name : str | None, optional
        Repository name. Default is None.
    window_days : int, optional
        Number of days to include in the export window. Default is 14.
    export_format : ExportFormat, optional
        Output format (JSON, CSV, etc.). Default is ExportFormat.JSON.
    output_path : str
        File path for the exported bundle.

    Returns
    -------
    str
        JSON-serialized export status response from the control plane.

    """
    target = ResourceTarget(scope=scope, estate_key=estate_key, owner=owner, name=name)
    sink = ExportSinkOptions(export_format=export_format, output_path=Path(output_path))
    return _api_placeholder(
        "bundle",
        **_flatten_target(target),
        window_days=window_days,
        **_flatten_sink(sink),
    )
