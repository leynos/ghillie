"""How the CLI presents a failure and which exit code it uses.

Every command ends a failure the same way: a rendered error on standard error
and one of two exit codes. Keeping that decision here means the command
functions carry no printing, no hint table, and no exit-code arithmetic.
"""

from __future__ import annotations

import sys
import typing as typ

from ghillie.cli.control_plane import ControlPlaneError
from ghillie.cli.estate_input import MAX_REQUEST_BODY_BYTES
from ghillie.cli.output import render_error
from ghillie.common.estate import NEW_ESTATE_KEY_PATTERN

if typ.TYPE_CHECKING:
    from ghillie.cli.config import OutputFormat
    from ghillie.cli.errors import LocalInputError

EXIT_LOCAL_INPUT = 2
"""Exit status for a request the CLI refused before sending it."""

EXIT_CONTROL_PLANE = 3
"""Exit status for a failed or malformed control-plane call."""

_HINTS = {
    "estate_not_found": (
        "Run `ghillie estate list` to see the estates this service knows about."
    ),
    "repository_not_found": (
        "Run `ghillie estate repo list --estate-key <key>` to see the "
        "registered repositories."
    ),
    "catalogue_invalid": (
        "Fix the listed catalogue issues and import the catalogue again."
    ),
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
        "The service returned a body that is not the documented JSON shape; "
        "check the service logs."
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


def hint_for(code: str) -> str:
    """Return the operator hint for *code*, or the generic fallback."""
    return _HINTS.get(code, _DEFAULT_HINT)


def local_failure(error: LocalInputError, *, output: OutputFormat) -> int:
    """Print a local-input failure and return its exit code.

    The hint is set when the failure is built, so nothing downstream mutates a
    shared error object.
    """
    failure = ControlPlaneError(
        error.code,
        error.message,
        hint=hint_for(error.code),
    )
    return _report(failure, output=output, exit_code=EXIT_LOCAL_INPUT)


def api_failure(error: ControlPlaneError, *, output: OutputFormat) -> int:
    """Print a control-plane failure and return its exit code."""
    return _report(
        _with_hint(error),
        output=output,
        exit_code=EXIT_CONTROL_PLANE,
    )


def _with_hint(error: ControlPlaneError) -> ControlPlaneError:
    """Return *error* with a hint, without changing the caller's object."""
    if error.hint:
        return error
    return ControlPlaneError(
        error.code,
        error.message,
        hint=hint_for(error.code),
        response=error.response,
    )


def _report(
    error: ControlPlaneError,
    *,
    output: OutputFormat,
    exit_code: int,
) -> int:
    """Write *error* to standard error and return *exit_code*."""
    print(render_error(error, output=output), file=sys.stderr)
    return exit_code
