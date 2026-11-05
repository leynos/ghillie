"""Import verb: wire contract, local rejection, and rendering.

The fake transport pins the request the CLI sends (method, path, query, and
body), every check that must reject an import before it is sent (D1, D16,
O5), and the two ways a successful import is rendered.
"""

from __future__ import annotations

import json
import typing as typ

import httpx
import pytest

from ghillie.cli.commands.estate import (
    MAX_REQUEST_BODY_BYTES,
    NEW_ESTATE_KEY_PATTERN,
    import_catalogue,
)
from ghillie.cli.control_plane import encode_json_body
from ghillie.estate.models import MAX_REQUEST_BODY_BYTES as SERVICE_BODY_LIMIT
from ghillie.estate.models import NEW_ESTATE_KEY_PATTERN as SERVICE_KEY_PATTERN
from tests.unit.cli.payloads import IMPORT_PAYLOAD, error_document

if typ.TYPE_CHECKING:
    from pathlib import Path

    from tests.unit.cli.harness import CliHarness


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


def test_import_posts_the_catalogue_document(
    harness: typ.Callable[..., CliHarness],
    catalogue_file: Path,
) -> None:
    """Import uploads the file, commit, and optional name as JSON."""
    client = harness()
    client.queue_json(IMPORT_PAYLOAD)

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
    client.queue_json(IMPORT_PAYLOAD)

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
    client.queue_json(IMPORT_PAYLOAD)

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
    client.queue_json({**IMPORT_PAYLOAD, "dry_run": True})

    client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=catalogue_file,
        commit_sha="c1",
        estate_name=None,
    )

    assert client.requests[0].url.params == httpx.QueryParams({"dry_run": "true"})


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
    error = error_document(capsys.readouterr().err)["error"]
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
    assert error_document(capsys.readouterr().err)["error"]["code"] == (
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
    error = error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "invalid_estate_key"
    assert NEW_ESTATE_KEY_PATTERN in error["hint"]


def test_local_constants_match_the_service() -> None:
    """The duplicated limit and pattern must not drift from the service."""
    assert MAX_REQUEST_BODY_BYTES == SERVICE_BODY_LIMIT
    assert NEW_ESTATE_KEY_PATTERN == SERVICE_KEY_PATTERN


class _BodyLimitCase(typ.NamedTuple):
    """One boundary case for the request-body limit."""

    offset: int
    is_accepted: bool


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(_BodyLimitCase(offset=-1, is_accepted=True), id="below-limit"),
        pytest.param(_BodyLimitCase(offset=0, is_accepted=True), id="at-limit"),
        pytest.param(_BodyLimitCase(offset=1, is_accepted=False), id="above-limit"),
    ],
)
def test_import_body_limit_boundary(
    harness: typ.Callable[..., CliHarness],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: _BodyLimitCase,
) -> None:
    """O5: the CLI accepts exactly the bodies the server would accept."""
    offset, is_accepted = case
    target = MAX_REQUEST_BODY_BYTES + offset
    document = _document_of_encoded_size(target)
    assert len(document) < target, "padding must make characters fewer than bytes"
    path = tmp_path / f"catalogue-{offset}.yaml"
    path.write_text(document, encoding="utf-8")
    client = harness(output="json")
    if is_accepted:
        client.queue_json(IMPORT_PAYLOAD)

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
        error = error_document(capsys.readouterr().err)["error"]
        assert error["code"] == "request_too_large"
        assert str(MAX_REQUEST_BODY_BYTES) in error["hint"]


def test_import_reports_a_skipped_commit_prominently(
    harness: typ.Callable[..., CliHarness],
    catalogue_file: Path,
) -> None:
    """A repeated commit is visible in table mode, not silently successful."""
    client = harness()
    client.queue_json(
        {
            **IMPORT_PAYLOAD,
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
    payload = {**IMPORT_PAYLOAD, "skipped": True, "skipped_reason": "x"}
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
