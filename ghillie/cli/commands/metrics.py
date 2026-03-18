"""Metrics noun commands for the packaged operator CLI."""

from __future__ import annotations

from cyclopts import App

from ghillie.cli.commands.params import (
    NiceMetricsOptions,
    ResourceScope,
    ResourceTarget,
)
from ghillie.cli.context import get_current_context
from ghillie.cli.control_plane import ControlPlaneClient
from ghillie.cli.output import render_output

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
    scope: ResourceScope,
    estate_key: str | None = None,
    owner: str | None = None,
    name: str | None = None,
    window_days: int = 14,
    group_by: str = "repo",
) -> str:
    """Return required MVP metrics for a selected window."""
    target = ResourceTarget(scope=scope, estate_key=estate_key, owner=owner, name=name)
    return _api_placeholder(
        "required",
        scope=target.scope,
        estate_key=target.estate_key or "",
        owner=target.owner or "",
        name=target.name or "",
        window_days=window_days,
        group_by=group_by,
    )


@metrics_app.command(name="nice")
def nice_metrics(  # noqa: PLR0913
    *,
    scope: ResourceScope,
    estate_key: str | None = None,
    owner: str | None = None,
    name: str | None = None,
    window_days: int = 14,
    include_comments: bool = False,
    include_commit_counts: bool = False,
    include_sloc_breakdown: bool = False,
) -> str:
    """Return optional MVP metrics when data is available."""
    target = ResourceTarget(scope=scope, estate_key=estate_key, owner=owner, name=name)
    opts = NiceMetricsOptions(
        include_comments=include_comments,
        include_commit_counts=include_commit_counts,
        include_sloc_breakdown=include_sloc_breakdown,
    )
    return _api_placeholder(
        "nice",
        scope=target.scope,
        estate_key=target.estate_key or "",
        owner=target.owner or "",
        name=target.name or "",
        window_days=window_days,
        include_comments=opts.include_comments,
        include_commit_counts=opts.include_commit_counts,
        include_sloc_breakdown=opts.include_sloc_breakdown,
    )
