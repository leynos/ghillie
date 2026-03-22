"""Report noun commands for the packaged operator CLI."""

from __future__ import annotations

from cyclopts import App

from ghillie.cli.commands.params import (
    ModelBackend,
    ReportRunOptions,
    ResourceScope,
    ResourceTarget,
)
from ghillie.cli.context import get_current_context
from ghillie.cli.control_plane import ControlPlaneClient
from ghillie.cli.output import render_output

report_app = App(name="report", help="Trigger and observe reporting runs.")


def _api_placeholder(verb: str, **fields: object) -> str:
    context = get_current_context()
    with ControlPlaneClient(context.config):
        return render_output(
            {
                "noun": "report",
                "verb": verb,
                "status": "not_implemented",
                "message": "not implemented in Task 2.5.a",
                **fields,
            },
            output=context.config.output,
        )


# @codescene(disable:"Excess Number of Function Arguments")
# 2026-03-22: CLI command entry point keeps explicit options for operator UX.
@report_app.command
def run(  # noqa: PLR0913
    *,
    scope: ResourceScope,
    estate_key: str | None = None,
    owner: str | None = None,
    name: str | None = None,
    window_days: int = 14,
    as_of: str | None = None,
    model_backend: ModelBackend = "mock",
    wait: bool = True,
) -> str:
    """Start a scaffolded reporting run."""
    target = ResourceTarget(scope=scope, estate_key=estate_key, owner=owner, name=name)
    opts = ReportRunOptions(as_of=as_of, model_backend=model_backend, wait=wait)
    return _api_placeholder(
        "run",
        scope=target.scope,
        estate_key=target.estate_key or "",
        owner=target.owner or "",
        name=target.name or "",
        window_days=window_days,
        as_of=opts.as_of or "",
        model_backend=opts.model_backend,
        wait=opts.wait,
    )


@report_app.command
def status(*, run_id: str) -> str:
    """Query one report run."""
    return _api_placeholder("status", run_id=run_id)


@report_app.command
def watch(*, run_id: str, poll_interval_s: float = 2.0) -> str:
    """Watch one report run."""
    return _api_placeholder(
        "watch",
        run_id=run_id,
        poll_interval_s=poll_interval_s,
    )
