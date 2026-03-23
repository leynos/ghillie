"""Estate noun commands for the packaged operator CLI."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from cyclopts import App

from ghillie.cli.context import get_current_context
from ghillie.cli.control_plane import ControlPlaneClient
from ghillie.cli.output import render_output

estate_app = App(name="estate", help="Manage estate configuration operations.")
repo_app = App(name="repo", help="Manage estate repository configuration.")


def _api_placeholder(noun: str, verb: str, **fields: object) -> str:
    context = get_current_context()
    with ControlPlaneClient(context.config):
        return render_output(
            {
                "noun": noun,
                "verb": verb,
                "status": "not_implemented",
                "message": "not implemented in Task 2.5.a",
                **fields,
            },
            output=context.config.output,
        )


@estate_app.command(name="import")
def import_catalogue(
    *,
    estate_key: str,
    catalogue_path: Path,
    commit_sha: str,
    estate_name: str | None = None,
) -> str:
    """Import catalogue definitions into estate storage."""
    return _api_placeholder(
        "estate",
        "import",
        estate_key=estate_key,
        catalogue_path=str(catalogue_path),
        commit_sha=commit_sha,
        estate_name=estate_name or "",
    )


@estate_app.command
def sync(*, estate_key: str, wait: bool = True) -> str:
    """Sync imported catalogue repositories into the registry."""
    return _api_placeholder("estate", "sync", estate_key=estate_key, wait=wait)


@estate_app.command(name="list")
def list_estates(*, active: bool = True, inactive: bool = False) -> str:
    """List estates known to the control plane."""
    return _api_placeholder(
        "estate",
        "list",
        active=active,
        inactive=inactive,
    )


# @codescene(disable:"Excess Number of Function Arguments")
# 2026-03-22: CLI command entry point keeps explicit options for operator UX.
@repo_app.command(name="list")
def list_repositories(  # noqa: PLR0913
    *,
    estate_key: str,
    active: bool = True,
    inactive: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """List repositories for one estate."""
    return _api_placeholder(
        "estate repo",
        "list",
        estate_key=estate_key,
        active=active,
        inactive=inactive,
        limit=limit,
        offset=offset,
    )


@repo_app.command(name="set")
def set_repository(
    *,
    owner: str,
    name: str,
    ingestion_enabled: bool,
) -> str:
    """Set per-repository ingestion state."""
    return _api_placeholder(
        "estate repo",
        "set",
        owner=owner,
        name=name,
        ingestion_enabled=ingestion_enabled,
    )


estate_app.command(repo_app)
