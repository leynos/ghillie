"""The client half of the O4 error contract.

Every non-2xx response, transport failure, timeout, and non-JSON body exits
``3`` with a non-empty code, message, and hint; a catalogue rejection also
carries its per-issue details.
"""

from __future__ import annotations

import typing as typ

import httpx
import pytest

from ghillie.cli.commands.estate import sync
from tests.unit.cli.payloads import error_document

if typ.TYPE_CHECKING:
    from tests.unit.cli.harness import CliHarness


class _ErrorCase(typ.NamedTuple):
    """One documented error row and the hint its code must produce."""

    status: int
    payload: dict[str, object]
    expected_code: str
    expected_hint: str


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _ErrorCase(
                404,
                {
                    "title": "Estate not found",
                    "description": "no estate with key 'missing'",
                    "code": "estate_not_found",
                },
                "estate_not_found",
                "estate list",
            ),
            id="estate-not-found",
        ),
        pytest.param(
            _ErrorCase(
                404,
                {
                    "title": "Repository not found",
                    "description": "no repository 'nobody/nothing'",
                    "code": "repository_not_found",
                },
                "repository_not_found",
                "repo list",
            ),
            id="repository-not-found",
        ),
        pytest.param(
            _ErrorCase(
                422,
                {
                    "title": "Catalogue rejected",
                    "description": "catalogue validation failed",
                    "code": "catalogue_invalid",
                    "issues": [{"code": "catalogue_schema", "message": "projects: 42"}],
                },
                "catalogue_invalid",
                "issues",
            ),
            id="catalogue-invalid",
        ),
        pytest.param(
            _ErrorCase(
                404,
                {
                    "title": "Not Found",
                    "description": "the route does not exist",
                    "code": "not_found",
                },
                "not_found",
                "GHILLIE_DATABASE_URL",
            ),
            id="route-missing",
        ),
        pytest.param(
            _ErrorCase(
                401,
                {
                    "title": "Unauthorized",
                    "description": "missing bearer token",
                    "code": "unauthorized",
                },
                "unauthorized",
                "GHILLIE_AUTH_TOKEN",
            ),
            id="unauthorized",
        ),
        pytest.param(
            _ErrorCase(
                413,
                {
                    "title": "Payload too large",
                    "description": "request body is too large",
                    "code": "payload_too_large",
                    "max_bytes": 1048576,
                },
                "payload_too_large",
                "bytes",
            ),
            id="payload-too-large",
        ),
        pytest.param(
            _ErrorCase(
                409,
                {
                    "title": "Conflict",
                    "description": "the estate changed concurrently",
                    "code": "conflict",
                },
                "conflict",
                "service logs",
            ),
            id="conflict",
        ),
        pytest.param(
            _ErrorCase(
                503,
                {
                    "title": "Storage unavailable",
                    "description": "the catalogue store is unavailable",
                    "code": "storage_unavailable",
                },
                "storage_unavailable",
                "service logs",
            ),
            id="storage-unavailable",
        ),
    ],
)
def test_http_error_maps_to_exit_3(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
    case: _ErrorCase,
) -> None:
    """O4: each documented error row yields exit 3 and its stable code."""
    status, payload, expected_code, expected_hint = case
    client = harness(output="json")
    client.queue_json(payload, status=status)

    result = client.invoke(sync, estate_key="demo")

    assert result == 3
    error = error_document(capsys.readouterr().err)["error"]
    assert error["code"] == expected_code
    assert error["message"], "the message must not be empty"
    assert expected_hint in error["hint"]
    assert error["status"] == status


def test_http_error_renders_catalogue_issues(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A catalogue rejection surfaces its per-issue codes and messages."""
    client = harness(output="json")
    client.queue_json(
        {
            "title": "Catalogue rejected",
            "description": "catalogue validation failed",
            "code": "catalogue_invalid",
            "issues": [{"code": "catalogue_schema", "message": "projects: 42"}],
        },
        status=422,
    )

    client.invoke(sync, estate_key="demo")

    assert error_document(capsys.readouterr().err)["error"]["issues"] == [
        {"code": "catalogue_schema", "message": "projects: 42"}
    ]


def test_unstructured_http_error_still_exits_3(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A body without a ``code`` falls back to the HTTP status."""
    client = harness(output="json")
    client.queue_json(
        {"title": "Internal Server Error", "description": "unexpected failure"},
        status=500,
    )

    assert client.invoke(sync, estate_key="demo") == 3
    error = error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "http_500"
    assert error["message"] == "unexpected failure"
    assert "service logs" in error["hint"]


def test_non_json_error_body_exits_3(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A proxy's HTML error page is still a structured CLI failure."""
    client = harness(output="json")
    client.queue_raw("<html>bad gateway</html>", status=502)

    assert client.invoke(sync, estate_key="demo") == 3
    error = error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "http_502"
    assert error["message"], "the reason phrase supplies a message"
    assert error["hint"]


def test_transport_failure_exits_3(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unreachable service is exit 3 with a base-URL hint."""
    client = harness(output="json")
    client.queue_error(httpx.ConnectError("connection refused"))

    assert client.invoke(sync, estate_key="demo") == 3
    error = error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "transport"
    assert "--api-base-url" in error["hint"]
    assert "connection refused" not in error["message"], (
        "transport detail is not echoed"
    )


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(httpx.TooManyRedirects("too many redirects"), id="redirects"),
        pytest.param(httpx.DecodingError("cannot decode"), id="decoding"),
    ],
)
def test_other_request_errors_exit_3(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
    failure: httpx.RequestError,
) -> None:
    """A request error that is not a transport error is still exit 3."""
    client = harness(output="json")
    client.queue_error(failure)

    assert client.invoke(sync, estate_key="demo") == 3
    error = error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "transport"
    assert error["hint"]


def test_timeout_exits_3(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A timeout says that retrying is safe, because import and sync are idempotent."""
    client = harness(output="json")
    client.queue_error(httpx.ReadTimeout("timed out"))

    assert client.invoke(sync, estate_key="demo") == 3
    error = error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "timeout"
    assert "re-running" in error["hint"]


def test_successful_non_json_body_exits_3(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A 200 that is not JSON is a protocol failure, not a success."""
    client = harness(output="json")
    client.queue_raw("not json", status=200)

    assert client.invoke(sync, estate_key="demo") == 3
    error = error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "invalid_response"
    assert error["hint"]
