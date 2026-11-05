"""Estate CLI verbs against a fake control plane.

The fake transport pins the wire contract (method, path, query, and body) for
every verb, the local checks that must reject a request before it is sent
(D5, D16, O5), and the client half of the error contract (O4): every non-2xx
response, transport failure, timeout, and non-JSON body exits ``3`` with a
non-empty code, message, and hint.
"""

from __future__ import annotations

import json
import typing as typ

import httpx
import pytest

from ghillie.cli.app import main as cli_main
from ghillie.cli.commands.estate import (
    MAX_REQUEST_BODY_BYTES,
    NEW_ESTATE_KEY_PATTERN,
    import_catalogue,
    list_estates,
    list_repositories,
    set_repository,
    sync,
)
from ghillie.cli.control_plane import encode_json_body
from ghillie.estate.models import MAX_REQUEST_BODY_BYTES as SERVICE_BODY_LIMIT
from ghillie.estate.models import NEW_ESTATE_KEY_PATTERN as SERVICE_KEY_PATTERN
from tests.unit.cli.harness import BASE_URL, CliHarness

if typ.TYPE_CHECKING:
    from pathlib import Path

_IMPORT_PAYLOAD: dict[str, object] = {
    "estate_key": "demo",
    "commit_sha": "c1",
    "state": "succeeded",
    "dry_run": False,
    "skipped": False,
    "skipped_reason": None,
    "registry_sync_required": True,
    "projects": {"created": 1, "updated": 0, "deleted": 0},
    "components": {"created": 2, "updated": 0, "deleted": 0},
    "repositories": {"created": 1, "updated": 0, "deleted": 0},
    "edges": {"created": 0, "updated": 0, "deleted": 0},
}

_SYNC_PAYLOAD: dict[str, object] = {
    "estate_key": "demo",
    "state": "succeeded",
    "dry_run": False,
    "repositories_created": 1,
    "repositories_updated": 0,
    "repositories_deactivated": 0,
    "repositories_conflicted": [],
    "repositories_left_disabled": [],
    "repositories_left_disabled_count": 0,
}

_ESTATE_LIST_PAYLOAD: dict[str, object] = {
    "items": [
        {
            "key": "demo",
            "name": "Demo Estate",
            "description": "Example estate",
            "last_import": {
                "commit_sha": "c1",
                "imported_at": "2026-11-05T09:30:00+00:00",
            },
        }
    ],
    "limit": 50,
    "offset": 0,
    "has_more": False,
    "next_offset": None,
}

_REPOSITORY_LIST_PAYLOAD: dict[str, object] = {
    "estate_key": "demo",
    "items": [
        {
            "owner": "leynos",
            "name": "wildside",
            "default_branch": "main",
            "ingestion_enabled": True,
            "documentation_paths": ["docs/"],
        }
    ],
    "limit": 10,
    "offset": 0,
    "has_more": False,
    "next_offset": None,
}

_TOGGLE_PAYLOAD: dict[str, object] = {
    "owner": "leynos",
    "name": "wildside",
    "ingestion_enabled": False,
    "changed": True,
}


@pytest.fixture
def catalogue_file(tmp_path: Path) -> Path:
    """Write a small catalogue document and return its path."""
    path = tmp_path / "catalogue.yaml"
    path.write_text("version: 1\n", encoding="utf-8")
    return path


def _error_document(standard_error: str) -> dict[str, typ.Any]:
    """Parse the structured error JSON the command wrote to standard error."""
    return typ.cast("dict[str, typ.Any]", json.loads(standard_error.strip()))


# ---------------------------------------------------------------------------
# Wire contract per verb
# ---------------------------------------------------------------------------


def test_import_posts_the_catalogue_document(
    harness: typ.Callable[..., CliHarness],
    catalogue_file: Path,
) -> None:
    """Import uploads the file, commit, and optional name as JSON."""
    client = harness()
    client.queue_json(_IMPORT_PAYLOAD)

    result = client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=catalogue_file,
        commit_sha="c1",
        estate_name="Demo Estate",
    )

    assert isinstance(result, str), "a successful table command returns text"
    request = client.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/estates/demo/catalogue-import"
    assert request.url.params == httpx.QueryParams(), "no query without a dry run"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "commit_sha": "c1",
        "catalogue_yaml": "version: 1\n",
        "estate_name": "Demo Estate",
    }


def test_import_omits_an_absent_estate_name(
    harness: typ.Callable[..., CliHarness],
    catalogue_file: Path,
) -> None:
    """An omitted name is left to the service instead of being sent as null."""
    client = harness()
    client.queue_json(_IMPORT_PAYLOAD)

    client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=catalogue_file,
        commit_sha="c1",
        estate_name=None,
    )

    assert json.loads(client.requests[0].content) == {
        "commit_sha": "c1",
        "catalogue_yaml": "version: 1\n",
    }


def test_import_strips_a_utf8_byte_order_mark(
    harness: typ.Callable[..., CliHarness],
    tmp_path: Path,
) -> None:
    """A BOM-prefixed catalogue is read as ``utf-8-sig`` (D1)."""
    path = tmp_path / "bom.yaml"
    path.write_text("\ufeffversion: 1\n", encoding="utf-8")
    client = harness()
    client.queue_json(_IMPORT_PAYLOAD)

    client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=path,
        commit_sha="c1",
        estate_name=None,
    )

    body = json.loads(client.requests[0].content)
    assert body["catalogue_yaml"] == "version: 1\n", "the BOM must not reach the server"


def test_import_dry_run_sets_the_query_parameter(
    harness: typ.Callable[..., CliHarness],
    catalogue_file: Path,
) -> None:
    """D20: the root dry-run option becomes ``?dry_run=true``."""
    client = harness(dry_run=True)
    client.queue_json({**_IMPORT_PAYLOAD, "dry_run": True})

    client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=catalogue_file,
        commit_sha="c1",
        estate_name=None,
    )

    assert client.requests[0].url.params == httpx.QueryParams({"dry_run": "true"})


def test_sync_posts_to_the_registry_sync_endpoint(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """D2: sync is one synchronous request with no wait option."""
    client = harness()
    client.queue_json(_SYNC_PAYLOAD)

    result = client.invoke(sync, estate_key="demo")

    assert isinstance(result, str)
    request = client.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/estates/demo/registry-sync"
    assert request.content == b"", "sync sends no body"


def test_sync_dry_run_sets_the_query_parameter(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """D20: sync honours the root dry-run option."""
    client = harness(dry_run=True)
    client.queue_json({**_SYNC_PAYLOAD, "dry_run": True})

    client.invoke(sync, estate_key="demo")

    assert client.requests[0].url.params == httpx.QueryParams({"dry_run": "true"})


def test_estate_list_gets_the_collection_without_filters(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """D4: estates have no lifecycle state, so the request carries no filter."""
    client = harness()
    client.queue_json(_ESTATE_LIST_PAYLOAD)

    result = client.invoke(list_estates)

    assert isinstance(result, str)
    request = client.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/estates"
    assert request.url.params == httpx.QueryParams()


def test_repo_list_passes_filters_and_pagination(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """D5: the filter and page bounds reach the server as documented."""
    client = harness()
    client.queue_json(_REPOSITORY_LIST_PAYLOAD)

    result = client.invoke(
        list_repositories,
        estate_key="demo",
        ingestion_enabled=True,
        limit=10,
        offset=5,
    )

    assert isinstance(result, str)
    request = client.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/estates/demo/repositories"
    assert request.url.params == httpx.QueryParams(
        {"ingestion_enabled": "true", "limit": "10", "offset": "5"}
    )


def test_repo_list_without_a_filter_lists_both_states(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """Neither flag lists everything; omitted filters stay off the wire."""
    client = harness()
    client.queue_json({**_REPOSITORY_LIST_PAYLOAD, "items": []})

    client.invoke(
        list_repositories,
        estate_key="demo",
        ingestion_enabled=None,
        limit=50,
        offset=0,
    )

    assert client.requests[0].url.params == httpx.QueryParams(
        {"limit": "50", "offset": "0"}
    )


def test_repo_set_patches_one_repository(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """D6: a toggle is a JSON merge-style PATCH on the repository."""
    client = harness()
    client.queue_json(_TOGGLE_PAYLOAD)

    result = client.invoke(
        set_repository,
        owner="leynos",
        name="wildside",
        ingestion_enabled=False,
    )

    assert isinstance(result, str)
    request = client.requests[0]
    assert request.method == "PATCH"
    assert request.url.path == "/repositories/leynos/wildside/ingestion"
    assert json.loads(request.content) == {"ingestion_enabled": False}


def test_repo_set_quotes_each_path_segment(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """A segment cannot escape its place in the path."""
    client = harness()
    client.queue_json(_TOGGLE_PAYLOAD)

    client.invoke(
        set_repository,
        owner="ley nos",
        name="wild/side",
        ingestion_enabled=True,
    )

    request = client.requests[0]
    assert request.url.raw_path == b"/repositories/ley%20nos/wild%2Fside/ingestion"


def test_repo_set_refuses_a_dry_run_without_sending_a_request(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ingestion PATCH has no dry-run mode, so a dry run must not mutate."""
    client = harness(dry_run=True, output="json")

    result = client.invoke(
        set_repository,
        owner="leynos",
        name="wildside",
        ingestion_enabled=False,
    )

    assert result == 2
    assert client.requests == [], "a dry run must never reach the service"
    error = _error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "dry_run_unsupported"
    assert "--dry-run" in error["hint"]


# ---------------------------------------------------------------------------
# Local rejection before any request
# ---------------------------------------------------------------------------


def test_import_rejects_a_missing_file(
    harness: typ.Callable[..., CliHarness],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unreadable path is local input, not a server failure."""
    client = harness(output="json")

    result = client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=tmp_path / "absent.yaml",
        commit_sha="c1",
        estate_name=None,
    )

    assert result == 2
    assert client.requests == [], "nothing should be sent"
    error = _error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "catalogue_file_unreadable"
    assert error["hint"]


def test_import_rejects_an_undecodable_file(
    harness: typ.Callable[..., CliHarness],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Invalid UTF-8 is reported as an unreadable catalogue file."""
    path = tmp_path / "binary.yaml"
    path.write_bytes(b"\xff\xfe\x00")
    client = harness(output="json")

    result = client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=path,
        commit_sha="c1",
        estate_name=None,
    )

    assert result == 2
    assert client.requests == []
    assert _error_document(capsys.readouterr().err)["error"]["code"] == (
        "catalogue_file_unreadable"
    )


@pytest.mark.parametrize("estate_key", ["", "-demo", ".demo", "demo/child", "x" * 65])
def test_import_rejects_an_invalid_estate_key(
    harness: typ.Callable[..., CliHarness],
    catalogue_file: Path,
    capsys: pytest.CaptureFixture[str],
    estate_key: str,
) -> None:
    """D16: the CLI applies the creation pattern before sending anything."""
    client = harness(output="json")

    result = client.invoke(
        import_catalogue,
        estate_key=estate_key,
        catalogue_path=catalogue_file,
        commit_sha="c1",
        estate_name=None,
    )

    assert result == 2
    assert client.requests == []
    error = _error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "invalid_estate_key"
    assert NEW_ESTATE_KEY_PATTERN in error["hint"]


def test_local_constants_match_the_service() -> None:
    """The duplicated limit and pattern must not drift from the service."""
    assert MAX_REQUEST_BODY_BYTES == SERVICE_BODY_LIMIT
    assert NEW_ESTATE_KEY_PATTERN == SERVICE_KEY_PATTERN


def _document_of_encoded_size(target: int) -> str:
    """Build a catalogue document whose JSON body is exactly *target* bytes.

    Multibyte characters and JSON-escaped newlines make the character count
    smaller than the byte count, so a check on characters instead of bytes
    cannot pass this test by accident (O5 non-vacuity).
    """
    base = "é" * 10 + "\n" * 10
    base_size = len(encode_json_body({"commit_sha": "c1", "catalogue_yaml": base}))
    padding = target - base_size
    assert padding >= 0, "the target must leave room for the envelope"
    return base + "a" * padding


@pytest.mark.parametrize(
    ("offset", "is_accepted"),
    [(-1, True), (0, True), (1, False)],
    ids=["below-limit", "at-limit", "above-limit"],
)
def test_import_body_limit_boundary(  # noqa: PLR0913
    harness: typ.Callable[..., CliHarness],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    offset: int,
    *,
    is_accepted: bool,
) -> None:
    """O5: the CLI accepts exactly the bodies the server would accept."""
    target = MAX_REQUEST_BODY_BYTES + offset
    document = _document_of_encoded_size(target)
    assert len(document) < target, "padding must make characters fewer than bytes"
    path = tmp_path / f"catalogue-{offset}.yaml"
    path.write_text(document, encoding="utf-8")
    client = harness(output="json")
    if is_accepted:
        client.queue_json(_IMPORT_PAYLOAD)

    result = client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=path,
        commit_sha="c1",
        estate_name=None,
    )

    if is_accepted:
        assert isinstance(result, str)
        assert len(client.requests[0].content) == target
    else:
        assert result == 2
        assert client.requests == []
        error = _error_document(capsys.readouterr().err)["error"]
        assert error["code"] == "request_too_large"
        assert str(MAX_REQUEST_BODY_BYTES) in error["hint"]


def test_repo_list_rejects_out_of_range_pagination(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """D5: pagination is validated locally and no request is sent."""
    client = harness()
    base = [
        "--api-base-url",
        BASE_URL,
        "estate",
        "repo",
        "list",
        "--estate-key",
        "demo",
    ]

    assert cli_main([*base, "--limit", "0"]) == 2
    assert cli_main([*base, "--limit", "501"]) == 2
    assert cli_main([*base, "--offset", "-1"]) == 2

    assert client.requests == [], "no request may be sent"
    captured = capsys.readouterr()
    assert captured.out == "", "validation errors go to standard error"
    assert captured.err


def test_repo_set_requires_a_toggle(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """D6: the toggle flag is required, so omitting both forms exits 2."""
    client = harness()

    result = cli_main(
        [
            "--api-base-url",
            BASE_URL,
            "estate",
            "repo",
            "set",
            "--owner",
            "leynos",
            "--name",
            "wildside",
        ]
    )

    assert result == 2
    assert client.requests == []
    assert capsys.readouterr().err


def test_estate_list_rejects_lifecycle_flags(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """D4: the removed ``--active/--inactive`` options are unknown, not ignored."""
    client = harness()

    result = cli_main(["--api-base-url", BASE_URL, "estate", "list", "--active"])

    assert result == 2
    assert client.requests == []
    assert capsys.readouterr().err


def test_sync_rejects_the_removed_wait_flag(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """D2: sync is synchronous, so ``--wait`` no longer exists."""
    client = harness()

    result = cli_main(
        ["--api-base-url", BASE_URL, "estate", "sync", "--estate-key", "demo", "--wait"]
    )

    assert result == 2
    assert client.requests == []
    assert capsys.readouterr().err


# ---------------------------------------------------------------------------
# O4 client half: every failure is exit 3 with code, message, and hint
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "payload", "expected_code", "expected_hint"),
    [
        (
            404,
            {
                "title": "Estate not found",
                "description": "no estate with key 'missing'",
                "code": "estate_not_found",
            },
            "estate_not_found",
            "estate list",
        ),
        (
            404,
            {
                "title": "Repository not found",
                "description": "no repository 'nobody/nothing'",
                "code": "repository_not_found",
            },
            "repository_not_found",
            "repo list",
        ),
        (
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
        (
            404,
            {
                "title": "Not Found",
                "description": "the route does not exist",
                "code": "not_found",
            },
            "not_found",
            "GHILLIE_DATABASE_URL",
        ),
        (
            401,
            {
                "title": "Unauthorized",
                "description": "missing bearer token",
                "code": "unauthorized",
            },
            "unauthorized",
            "GHILLIE_AUTH_TOKEN",
        ),
        (
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
        (
            409,
            {
                "title": "Conflict",
                "description": "the estate changed concurrently",
                "code": "conflict",
            },
            "conflict",
            "service logs",
        ),
        (
            503,
            {
                "title": "Storage unavailable",
                "description": "the catalogue store is unavailable",
                "code": "storage_unavailable",
            },
            "storage_unavailable",
            "service logs",
        ),
    ],
)
def test_http_error_maps_to_exit_3(  # noqa: PLR0913
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
    status: int,
    payload: dict[str, object],
    expected_code: str,
    expected_hint: str,
) -> None:
    """O4: each documented error row yields exit 3 and its stable code."""
    client = harness(output="json")
    client.queue_json(payload, status=status)

    result = client.invoke(sync, estate_key="demo")

    assert result == 3
    error = _error_document(capsys.readouterr().err)["error"]
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

    assert _error_document(capsys.readouterr().err)["error"]["issues"] == [
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
    error = _error_document(capsys.readouterr().err)["error"]
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
    error = _error_document(capsys.readouterr().err)["error"]
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
    error = _error_document(capsys.readouterr().err)["error"]
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
    error = _error_document(capsys.readouterr().err)["error"]
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
    error = _error_document(capsys.readouterr().err)["error"]
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
    error = _error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "invalid_response"
    assert error["hint"]


# ---------------------------------------------------------------------------
# Rendering contracts
# ---------------------------------------------------------------------------


def test_import_reports_a_skipped_commit_prominently(
    harness: typ.Callable[..., CliHarness],
    catalogue_file: Path,
) -> None:
    """A repeated commit is visible in table mode, not silently successful."""
    client = harness()
    client.queue_json(
        {
            **_IMPORT_PAYLOAD,
            "skipped": True,
            "skipped_reason": "commit_already_imported",
            "registry_sync_required": False,
        }
    )

    result = client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=catalogue_file,
        commit_sha="c1",
        estate_name=None,
    )

    assert isinstance(result, str)
    first_line = result.splitlines()[0]
    assert first_line.startswith("SKIPPED")
    assert "commit_already_imported" in first_line


def test_import_json_returns_the_server_document(
    harness: typ.Callable[..., CliHarness],
    catalogue_file: Path,
) -> None:
    """JSON success output is the server document unchanged (D7)."""
    payload = {**_IMPORT_PAYLOAD, "skipped": True, "skipped_reason": "x"}
    client = harness(output="json")
    client.queue_json(payload)

    result = client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=catalogue_file,
        commit_sha="c1",
        estate_name=None,
    )

    assert json.loads(typ.cast("str", result)) == payload


def test_estate_list_table_names_each_estate(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """The table output is readable: a header plus one row per estate."""
    client = harness()
    client.queue_json(_ESTATE_LIST_PAYLOAD)

    result = typ.cast("str", client.invoke(list_estates))

    lines = result.splitlines()
    assert "KEY" in lines[0]
    assert "NAME" in lines[0]
    assert any("demo" in line and "Demo Estate" in line for line in lines)
    assert any("has_more=false" in line for line in lines)


def test_repo_list_table_names_each_repository(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """Repositories render with their ingestion state."""
    client = harness()
    client.queue_json(_REPOSITORY_LIST_PAYLOAD)

    result = typ.cast(
        "str",
        client.invoke(
            list_repositories,
            estate_key="demo",
            ingestion_enabled=None,
            limit=50,
            offset=0,
        ),
    )

    lines = result.splitlines()
    assert "OWNER" in lines[0]
    assert "INGESTION" in lines[0]
    assert any(
        "leynos" in line and "wildside" in line and "true" in line for line in lines
    )
