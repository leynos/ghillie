"""Estate noun commands for the packaged operator CLI.

Every verb is a thin HTTP call. Local validation rejects bad input before a
request is sent (D5, D16, O5); every control-plane failure is rendered with a
stable code, a message, and a next-step hint, then exits ``3`` (D7, O4).
"""

from __future__ import annotations

import re
import sys
import typing as typ
from pathlib import Path  # noqa: TC003 - Cyclopts resolves the annotation at runtime.

from cyclopts import App, Parameter, validators

from ghillie.cli.context import get_current_context
from ghillie.cli.control_plane import (
    ControlPlaneClient,
    ControlPlaneError,
    encode_json_body,
)
from ghillie.cli.output import (
    Column,
    render_collection,
    render_document,
    render_error,
)

estate_app = App(name="estate", help="Manage estate configuration operations.")
repo_app = App(name="repo", help="Manage estate repository configuration.")

MAX_REQUEST_BODY_BYTES = 1024 * 1024
"""Largest request body the service accepts (O5).

Duplicated from :mod:`ghillie.estate.models` because the CLI must not import
the server package (O6); :mod:`tests.unit.cli.test_estate_commands` asserts the
two values and the two key patterns stay equal.
"""

NEW_ESTATE_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
"""Pattern a new estate key must match (D16), duplicated for the same reason."""

_NEW_ESTATE_KEY_RE = re.compile(NEW_ESTATE_KEY_PATTERN)

_EXIT_LOCAL_INPUT = 2
_EXIT_CONTROL_PLANE = 3

_HINTS = {
    "estate_not_found": (
        "Run `ghillie estate list` to see the estates this service knows about."
    ),
    "repository_not_found": (
        "Run `ghillie estate repo list --estate-key <key>` to see the "
        "registered repositories."
    ),
    "catalogue_invalid": "Fix the issues listed above and import the catalogue again.",
    "not_found": (
        "The endpoint is unavailable; the service may be running in health-only "
        "mode. Check that GHILLIE_DATABASE_URL is set."
    ),
    "transport": "Check --api-base-url and that the Ghillie service is running.",
    "timeout": "The operation may have completed; re-running it is safe.",
    "unauthorized": "Set --auth-token or GHILLIE_AUTH_TOKEN.",
    "payload_too_large": (
        "The request body exceeds the service limit in bytes; shorten the "
        "catalogue and retry."
    ),
    "invalid_response": (
        "The service returned a body that is not JSON; check the service logs."
    ),
    "conflict": "Retry the operation; if it persists, see the service logs.",
    "storage_unavailable": "The catalogue store is unavailable; see the service logs.",
    "catalogue_file_unreadable": (
        "Check that --catalogue-path names a readable UTF-8 file."
    ),
    "invalid_estate_key": f"Estate keys must match {NEW_ESTATE_KEY_PATTERN}.",
    "dry_run_unsupported": (
        "Remove --dry-run (or GHILLIE_DRY_RUN) to apply this change."
    ),
    "request_too_large": (
        f"The serialized request must be at most {MAX_REQUEST_BODY_BYTES} bytes; "
        "shorten the catalogue."
    ),
}
_DEFAULT_HINT = "See the service logs for details."

IngestionFilter = typ.Annotated[
    bool | None,
    Parameter(
        name=["--ingestion-enabled", "--active"],
        negative=["--ingestion-disabled", "--inactive"],
    ),
]
"""D5: one tri-state filter; neither flag lists both states."""

PageLimit = typ.Annotated[int, Parameter(validator=validators.Number(gte=1, lte=500))]
PageOffset = typ.Annotated[int, Parameter(validator=validators.Number(gte=0))]

ToggleFlag = typ.Annotated[
    bool,
    Parameter(name="--ingestion-enabled", negative="--ingestion-disabled"),
]
"""D6: a required toggle with both spellings."""

_ESTATE_COLUMNS: tuple[Column, ...] = (
    ("key", "KEY"),
    ("name", "NAME"),
    ("description", "DESCRIPTION"),
    ("last_import.commit_sha", "COMMIT"),
    ("last_import.imported_at", "IMPORTED"),
)
_REPOSITORY_COLUMNS: tuple[Column, ...] = (
    ("owner", "OWNER"),
    ("name", "NAME"),
    ("default_branch", "BRANCH"),
    ("ingestion_enabled", "INGESTION"),
)


def _hint_for(code: str) -> str:
    """Return the operator hint for *code*, or the generic fallback."""
    return _HINTS.get(code, _DEFAULT_HINT)


def _local_failure(code: str, message: str) -> int:
    """Print a local-input error and return exit code ``2``."""
    output = get_current_context().config.output
    error = ControlPlaneError(code, message, hint=_hint_for(code))
    print(render_error(error, output=output), file=sys.stderr)
    return _EXIT_LOCAL_INPUT


def _api_failure(error: ControlPlaneError) -> int:
    """Print a control-plane error and return exit code ``3``."""
    if not error.hint:
        error.hint = _hint_for(error.code)
    output = get_current_context().config.output
    print(render_error(error, output=output), file=sys.stderr)
    return _EXIT_CONTROL_PLANE


def _dry_run_params() -> dict[str, str] | None:
    """Return the D20 query parameter, or ``None`` to leave the URL clean."""
    return {"dry_run": "true"} if get_current_context().config.dry_run else None


def _call(
    method: str,
    path_segments: typ.Sequence[str],
    *,
    params: typ.Mapping[str, str] | None = None,
    body: typ.Mapping[str, object] | bytes | None = None,
) -> tuple[dict[str, object] | None, int | None]:
    """Perform one request, returning ``(document, failure_exit_code)``."""
    context = get_current_context()
    try:
        with ControlPlaneClient(context.config) as client:
            document = client.request_json(
                method, path_segments, params=params, body=body
            )
    except ControlPlaneError as error:
        return None, _api_failure(error)
    return document, None


def _render_page(
    document: typ.Mapping[str, object],
    *,
    columns: typ.Sequence[Column],
) -> str:
    """Render a paginated document through :func:`render_collection`."""
    raw_items = document.get("items")
    items = (
        [typ.cast("typ.Mapping[str, object]", item) for item in raw_items]
        if isinstance(raw_items, list)
        else []
    )
    meta = {key: value for key, value in document.items() if key != "items"}
    return render_collection(
        items,
        columns=columns,
        output=get_current_context().config.output,
        meta=meta,
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
    if not _NEW_ESTATE_KEY_RE.fullmatch(estate_key):
        return _local_failure(
            "invalid_estate_key",
            f"estate key '{estate_key}' must match {NEW_ESTATE_KEY_PATTERN}",
        )
    try:
        catalogue_yaml = catalogue_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return _local_failure(
            "catalogue_file_unreadable",
            f"cannot read catalogue file '{catalogue_path}': {exc}",
        )

    body: dict[str, object] = {
        "commit_sha": commit_sha,
        "catalogue_yaml": catalogue_yaml,
    }
    if estate_name is not None:
        body["estate_name"] = estate_name
    encoded = encode_json_body(body)
    if len(encoded) > MAX_REQUEST_BODY_BYTES:
        return _local_failure(
            "request_too_large",
            f"the request body is {len(encoded)} bytes; the limit is "
            f"{MAX_REQUEST_BODY_BYTES}",
        )

    document, failure = _call(
        "POST",
        ["estates", estate_key, "catalogue-import"],
        params=_dry_run_params(),
        body=encoded,
    )
    if failure is not None:
        return failure

    output = get_current_context().config.output
    rendered = render_document(typ.cast("dict[str, object]", document), output=output)
    if output == "table" and document is not None and document.get("skipped") is True:
        reason = document.get("skipped_reason") or "already imported"
        return (
            f"SKIPPED: commit {commit_sha} was not imported ({reason}).\n\n{rendered}"
        )
    return rendered


@estate_app.command
def sync(*, estate_key: str) -> int | str:
    """Sync imported catalogue repositories into the registry (D2)."""
    document, failure = _call(
        "POST",
        ["estates", estate_key, "registry-sync"],
        params=_dry_run_params(),
    )
    if failure is not None:
        return failure
    return render_document(
        typ.cast("dict[str, object]", document),
        output=get_current_context().config.output,
    )


@estate_app.command(name="list")
def list_estates() -> int | str:
    """List estates known to the control plane (D4)."""
    document, failure = _call("GET", ["estates"])
    if failure is not None:
        return failure
    return _render_page(
        typ.cast("dict[str, object]", document), columns=_ESTATE_COLUMNS
    )


@repo_app.command(name="list")
def list_repositories(
    *,
    estate_key: str,
    ingestion_enabled: IngestionFilter = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> int | str:
    """List repositories for one estate (D5)."""
    params = {"limit": str(limit), "offset": str(offset)}
    if ingestion_enabled is not None:
        params["ingestion_enabled"] = "true" if ingestion_enabled else "false"
    document, failure = _call(
        "GET",
        ["estates", estate_key, "repositories"],
        params=params,
    )
    if failure is not None:
        return failure
    return _render_page(
        typ.cast("dict[str, object]", document), columns=_REPOSITORY_COLUMNS
    )


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
    if get_current_context().config.dry_run:
        return _local_failure(
            "dry_run_unsupported",
            "`estate repo set` has no dry-run mode; re-run without --dry-run "
            "to apply the toggle",
        )
    document, failure = _call(
        "PATCH",
        ["repositories", owner, name, "ingestion"],
        body={"ingestion_enabled": ingestion_enabled},
    )
    if failure is not None:
        return failure
    return render_document(
        typ.cast("dict[str, object]", document),
        output=get_current_context().config.output,
    )


estate_app.command(repo_app)
