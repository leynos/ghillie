"""Estate noun commands for the packaged operator CLI.

Each command reads the invocation context once, delegates the work, and hands
any failure to :mod:`ghillie.cli.presentation`. Local validation lives in
:mod:`ghillie.cli.estate_input`, rendering in :mod:`ghillie.cli.estate_view`,
and the page shape check in :mod:`ghillie.cli.control_plane` (D5, D16, O4,
O5).
"""

from __future__ import annotations

import http
import typing as typ
from pathlib import Path  # noqa: TC003 - Cyclopts resolves the annotation at runtime.

from cyclopts import App, Parameter, validators

from ghillie.cli.context import CommandContext, get_current_context
from ghillie.cli.control_plane import (
    ControlPlaneError,
    ControlPlanePage,
    ControlPlaneRequest,
)
from ghillie.cli.errors import LocalInputError
from ghillie.cli.estate_input import import_body
from ghillie.cli.estate_view import (
    ESTATE_COLUMNS,
    REPOSITORY_COLUMNS,
    render_import,
    render_page,
)
from ghillie.cli.output import render_document
from ghillie.cli.presentation import api_failure, local_failure
from ghillie.common.estate import MAX_PAGE_OFFSET

if typ.TYPE_CHECKING:
    from ghillie.cli.config import ResolvedCliConfig

estate_app = App(name="estate", help="Manage estate configuration operations.")
repo_app = App(name="repo", help="Manage estate repository configuration.")

IngestionFilter = typ.Annotated[
    bool | None,
    Parameter(
        name=["--ingestion-enabled", "--active"],
        negative=["--ingestion-disabled", "--inactive"],
    ),
]
"""D5: one tri-state filter; neither flag lists both states."""

PageLimit = typ.Annotated[int, Parameter(validator=validators.Number(gte=1, lte=500))]
PageOffset = typ.Annotated[
    int, Parameter(validator=validators.Number(gte=0, lte=MAX_PAGE_OFFSET))
]

ToggleFlag = typ.Annotated[
    bool,
    Parameter(name="--ingestion-enabled", negative="--ingestion-disabled"),
]
"""D6: a required toggle with both spellings."""


def _dry_run_params(config: ResolvedCliConfig) -> dict[str, str] | None:
    """Return the D20 query parameter, or ``None`` to leave the URL clean."""
    return {"dry_run": "true"} if config.dry_run else None


def _call(
    context: CommandContext,
    request: ControlPlaneRequest,
) -> dict[str, object]:
    """Perform one request through the context's client factory.

    Raises
    ------
    ControlPlaneError
        If the call fails or the response is not a JSON object.

    """
    with context.client_factory(context.config) as client:
        return client.request_json(
            request.method,
            request.path_segments,
            params=request.params,
            body=request.body,
        )


def _page(
    context: CommandContext,
    request: ControlPlaneRequest,
) -> ControlPlanePage:
    """Fetch and validate one page through the context's client factory."""
    with context.client_factory(context.config) as client:
        return client.request_page(
            request.method, request.path_segments, params=request.params
        )


@estate_app.command(name="import")
def import_catalogue(
    *,
    estate_key: str,
    catalogue_path: Path,
    commit_sha: str,
    estate_name: str | None = None,
) -> int | str:
    """Import catalogue definitions into estate storage.

    The file is read locally as ``utf-8-sig`` and uploaded as JSON (D1). The
    estate key, the file, and the serialized size are all checked before the
    request is sent, so a bad invocation never reaches the service.
    """
    context = get_current_context()
    output = context.config.output
    try:
        encoded = import_body(
            estate_key,
            catalogue_path,
            commit_sha=commit_sha,
            estate_name=estate_name,
        )
        document = _call(
            context,
            ControlPlaneRequest(
                http.HTTPMethod.POST,
                ("estates", estate_key, "catalogue-import"),
                params=_dry_run_params(context.config),
                body=encoded,
            ),
        )
    except LocalInputError as error:
        return local_failure(error, output=output)
    except ControlPlaneError as error:
        return api_failure(error, output=output)
    return render_import(document, commit_sha=commit_sha, output=output)


@estate_app.command
def sync(*, estate_key: str) -> int | str:
    """Sync imported catalogue repositories into the registry (D2)."""
    context = get_current_context()
    output = context.config.output
    try:
        document = _call(
            context,
            ControlPlaneRequest(
                http.HTTPMethod.POST,
                ("estates", estate_key, "registry-sync"),
                params=_dry_run_params(context.config),
            ),
        )
    except ControlPlaneError as error:
        return api_failure(error, output=output)
    return render_document(document, output=output)


@estate_app.command(name="list")
def list_estates() -> int | str:
    """List estates known to the control plane (D4)."""
    context = get_current_context()
    output = context.config.output
    try:
        page = _page(context, ControlPlaneRequest(http.HTTPMethod.GET, ("estates",)))
    except ControlPlaneError as error:
        return api_failure(error, output=output)
    return render_page(page, columns=ESTATE_COLUMNS, output=output)


@repo_app.command(name="list")
def list_repositories(
    *,
    estate_key: str,
    ingestion_enabled: IngestionFilter = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> int | str:
    """List repositories for one estate (D5)."""
    context = get_current_context()
    output = context.config.output
    params = {"limit": str(limit), "offset": str(offset)}
    if ingestion_enabled is not None:
        params["ingestion_enabled"] = "true" if ingestion_enabled else "false"
    try:
        page = _page(
            context,
            ControlPlaneRequest(
                http.HTTPMethod.GET,
                ("estates", estate_key, "repositories"),
                params=params,
            ),
        )
    except ControlPlaneError as error:
        return api_failure(error, output=output)
    return render_page(page, columns=REPOSITORY_COLUMNS, output=output)


@repo_app.command(name="set")
def set_repository(
    *,
    owner: str,
    name: str,
    ingestion_enabled: ToggleFlag,
) -> int | str:
    """Set per-repository ingestion state (D6).

    The ingestion endpoint has no dry-run mode (D20 covers import and sync
    only), and a global ``--dry-run`` must never become a live mutation. The
    command therefore refuses locally rather than quietly applying the toggle.
    """
    context = get_current_context()
    output = context.config.output
    if context.config.dry_run:
        return local_failure(
            LocalInputError(
                "dry_run_unsupported",
                "`estate repo set` has no dry-run mode; re-run without --dry-run "
                "to apply the toggle",
            ),
            output=output,
        )
    try:
        document = _call(
            context,
            ControlPlaneRequest(
                http.HTTPMethod.PATCH,
                ("repositories", owner, name, "ingestion"),
                body={"ingestion_enabled": ingestion_enabled},
            ),
        )
    except ControlPlaneError as error:
        return api_failure(error, output=output)
    return render_document(document, output=output)


estate_app.command(repo_app)
