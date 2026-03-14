"""Ingest noun commands for the packaged operator CLI."""

from __future__ import annotations

import typing as typ

from cyclopts import App

from ghillie.cli.context import get_current_context
from ghillie.cli.control_plane import ControlPlaneClient
from ghillie.cli.output import render_output

IngestScope = typ.Literal["repository", "estate"]

ingest_app = App(name="ingest", help="Trigger and observe ingestion runs.")


def _api_placeholder(verb: str, **fields: object) -> str:
    context = get_current_context()
    with ControlPlaneClient(context.config):
        return render_output(
            {
                "noun": "ingest",
                "verb": verb,
                "status": "not_implemented",
                "message": "not implemented in Task 2.5.a",
                **fields,
            },
            output=context.config.output,
        )


@ingest_app.command
def run(  # noqa: PLR0913
    *,
    scope: IngestScope,
    estate_key: str | None = None,
    owner: str | None = None,
    name: str | None = None,
    lookback_days: int = 14,
    max_events_per_kind: int | None = None,
    wait: bool = True,
) -> str:
    """Start a scaffolded ingestion run."""
    return _api_placeholder(
        "run",
        scope=scope,
        estate_key=estate_key or "",
        owner=owner or "",
        name=name or "",
        lookback_days=lookback_days,
        max_events_per_kind=max_events_per_kind or "service-default",
        wait=wait,
    )


@ingest_app.command
def status(*, run_id: str) -> str:
    """Fetch status for one ingestion run."""
    return _api_placeholder("status", run_id=run_id)


@ingest_app.command
def watch(*, run_id: str, poll_interval_s: float = 2.0) -> str:
    """Poll a scaffolded ingestion run."""
    return _api_placeholder(
        "watch",
        run_id=run_id,
        poll_interval_s=poll_interval_s,
    )
