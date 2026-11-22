"""Failure presentation: hints, exit codes, and no mutation of the input."""

from __future__ import annotations

import json
import typing as typ

from ghillie.cli.control_plane import (
    ControlPlaneError,
    ControlPlaneIssue,
    ControlPlaneResponse,
)
from ghillie.cli.errors import LocalInputError
from ghillie.cli.presentation import (
    EXIT_CONTROL_PLANE,
    EXIT_LOCAL_INPUT,
    api_failure,
    hint_for,
    local_failure,
)

if typ.TYPE_CHECKING:
    import pytest


def _error_document(stderr: str) -> dict[str, object]:
    """Parse the JSON error envelope the CLI wrote to standard error."""
    return json.loads(stderr)["error"]


def test_hint_for_returns_the_documented_hint() -> None:
    """A known code gets its own next step."""
    assert "ghillie estate list" in hint_for("estate_not_found")


def test_hint_for_falls_back_for_an_unknown_code() -> None:
    """An undocumented code still tells the operator where to look."""
    assert hint_for("something_new") == "See the service logs for details."


def test_local_failure_prints_and_returns_exit_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A local failure carries its code, message and hint at exit 2."""
    result = local_failure(
        LocalInputError("invalid_estate_key", "the key is wrong"), output="json"
    )

    assert result == EXIT_LOCAL_INPUT
    error = _error_document(capsys.readouterr().err)
    assert error["code"] == "invalid_estate_key"
    assert error["message"] == "the key is wrong"
    assert "Estate keys must match" in str(error["hint"])


def test_api_failure_prints_and_returns_exit_3(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A control-plane failure keeps its status and issues at exit 3."""
    error = ControlPlaneError(
        "catalogue_invalid",
        "catalogue validation failed",
        response=ControlPlaneResponse(
            422, (ControlPlaneIssue("catalogue_schema", "projects: 42"),)
        ),
    )

    result = api_failure(error, output="json")

    assert result == EXIT_CONTROL_PLANE
    rendered = _error_document(capsys.readouterr().err)
    assert rendered["status"] == 422
    assert rendered["issues"] == [
        {"code": "catalogue_schema", "message": "projects: 42"}
    ]
    assert "issues" in str(rendered["hint"])


def test_api_failure_does_not_mutate_the_given_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The hint is added to a copy, so a caller's error object stays untouched."""
    error = ControlPlaneError("transport", "could not reach the control plane")
    assert error.hint is None

    api_failure(error, output="json")

    capsys.readouterr()
    assert error.hint is None, "presentation must not mutate the caller's error"


def test_api_failure_keeps_a_hint_the_client_already_set(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A specific hint from the client wins over the generic table."""
    error = ControlPlaneError("conflict", "conflict", hint="retry later")

    api_failure(error, output="json")

    assert _error_document(capsys.readouterr().err)["hint"] == "retry later"
