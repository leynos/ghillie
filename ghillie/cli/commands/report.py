"""Report noun commands for the packaged operator CLI."""

from __future__ import annotations

import typing as typ

from cyclopts import App

from ghillie.cli.context import get_current_context
from ghillie.cli.control_plane import ControlPlaneClient
from ghillie.cli.output import render_output

ReportScope = typ.Literal["repository", "estate"]
ModelBackend = typ.Literal["mock", "openai"]

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


@report_app.command
def run(  # noqa: PLR0913
    *,
    scope: ReportScope,
    estate_key: str | None = None,
    owner: str | None = None,
    name: str | None = None,
    window_days: int = 14,
    as_of: str | None = None,
    model_backend: ModelBackend = "mock",
    wait: bool = True,
) -> str:
    """Start a scaffolded reporting run."""
    return _api_placeholder(
        "run",
        scope=scope,
        estate_key=estate_key or "",
        owner=owner or "",
        name=name or "",
        window_days=window_days,
        as_of=as_of or "",
        model_backend=model_backend,
        wait=wait,
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
