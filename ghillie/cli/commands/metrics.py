"""Metrics noun commands for the packaged operator CLI."""

from __future__ import annotations

import typing as typ

from cyclopts import App

from ghillie.cli.context import get_current_context
from ghillie.cli.control_plane import ControlPlaneClient
from ghillie.cli.output import render_output

MetricsScope = typ.Literal["repository", "estate"]

metrics_app = App(name="metrics", help="Query MVP metrics views.")


def _api_placeholder(verb: str, **fields: object) -> str:
    context = get_current_context()
    with ControlPlaneClient(context.config):
        return render_output(
            {
                "noun": "metrics",
                "verb": verb,
                "status": "not_implemented",
                "message": "not implemented in Task 2.5.a",
                **fields,
            },
            output=context.config.output,
        )


@metrics_app.command(name="required")
def required_metrics(  # noqa: PLR0913
    *,
    scope: MetricsScope,
    estate_key: str | None = None,
    owner: str | None = None,
    name: str | None = None,
    window_days: int = 14,
    group_by: str = "repo",
) -> str:
    """Return required MVP metrics for a selected window."""
    return _api_placeholder(
        "required",
        scope=scope,
        estate_key=estate_key or "",
        owner=owner or "",
        name=name or "",
        window_days=window_days,
        group_by=group_by,
    )


@metrics_app.command(name="nice")
def nice_metrics(  # noqa: PLR0913
    *,
    scope: MetricsScope,
    estate_key: str | None = None,
    owner: str | None = None,
    name: str | None = None,
    window_days: int = 14,
    include_comments: bool = False,
    include_commit_counts: bool = False,
    include_sloc_breakdown: bool = False,
) -> str:
    """Return optional MVP metrics when data is available."""
    return _api_placeholder(
        "nice",
        scope=scope,
        estate_key=estate_key or "",
        owner=owner or "",
        name=name or "",
        window_days=window_days,
        include_comments=include_comments,
        include_commit_counts=include_commit_counts,
        include_sloc_breakdown=include_sloc_breakdown,
    )
