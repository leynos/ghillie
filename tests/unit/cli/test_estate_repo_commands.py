"""Repository list and toggle verbs.

D5 makes the ingestion filter tri-state and bounds pagination; D6 makes the
toggle required and both spellings explicit. ``repo set`` has no dry-run mode,
so a global dry run must be refused locally (D20). Path segments are quoted so
an owner or name cannot change the route.
"""

from __future__ import annotations

import json
import typing as typ

import httpx
import pytest

from ghillie.cli.app import main as cli_main
from ghillie.cli.commands.estate import (
    MAX_PAGE_OFFSET,
    list_repositories,
    set_repository,
)
from ghillie.estate.models import MAX_PAGE_OFFSET as SERVICE_MAX_PAGE_OFFSET
from tests.unit.cli.harness import BASE_URL, CliHarness
from tests.unit.cli.payloads import (
    REPOSITORY_LIST_PAYLOAD,
    TOGGLE_PAYLOAD,
    error_document,
)


def test_repo_list_passes_filters_and_pagination(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """D5: the filter and page bounds reach the server as documented."""
    client = harness()
    client.queue_json(REPOSITORY_LIST_PAYLOAD)

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
    client.queue_json({**REPOSITORY_LIST_PAYLOAD, "items": []})

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
    # The service rejects an offset above its signed-32-bit ceiling; the CLI
    # must not spend a request learning what it can reject locally (D16, O5).
    assert cli_main([*base, "--offset", str(MAX_PAGE_OFFSET + 1)]) == 2

    assert client.requests == [], "no request may be sent"
    captured = capsys.readouterr()
    assert captured.out == "", "validation errors go to standard error"
    assert captured.err


def test_repo_list_accepts_the_largest_offset(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ceiling itself is valid, so the bound cannot be off by one.

    The value must reach the command through the parser: calling the command
    directly would bypass the Cyclopts validator the bound lives in, and the
    test would pass even if the ceiling were missing.
    """
    client = harness(output="json")
    client.queue_json({**REPOSITORY_LIST_PAYLOAD, "items": []})

    exit_code = cli_main(
        [
            "--api-base-url",
            BASE_URL,
            "--output",
            "json",
            "estate",
            "repo",
            "list",
            "--estate-key",
            "demo",
            "--offset",
            str(MAX_PAGE_OFFSET),
        ]
    )

    assert exit_code == 0, capsys.readouterr().err
    assert client.requests[0].url.params["offset"] == str(MAX_PAGE_OFFSET)


def test_repo_list_offset_ceiling_matches_the_service() -> None:
    """The CLI duplicates the service ceiling, so the pair must stay equal."""
    assert MAX_PAGE_OFFSET == SERVICE_MAX_PAGE_OFFSET


def test_repo_list_table_names_each_repository(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """Repositories render with their ingestion state."""
    client = harness()
    client.queue_json(REPOSITORY_LIST_PAYLOAD)

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


def test_repo_set_patches_one_repository(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """D6: a toggle is a JSON merge-style PATCH on the repository."""
    client = harness()
    client.queue_json(TOGGLE_PAYLOAD)

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
    client.queue_json(TOGGLE_PAYLOAD)

    client.invoke(
        set_repository,
        owner="ley nos",
        name="wild/side",
        ingestion_enabled=True,
    )

    request = client.requests[0]
    assert request.url.raw_path == b"/repositories/ley%20nos/wild%2Fside/ingestion"


@pytest.mark.parametrize("estate_key", [pytest.param("..", id="two-dots"), "."])
def test_repo_list_encodes_a_dot_only_estate_key(
    harness: typ.Callable[..., CliHarness],
    estate_key: str,
) -> None:
    """A legacy dot-only key stays a path segment, not a normalised dot.

    ``quote(..., safe="")`` leaves dots alone, so ``..`` would build
    ``/estates/../repositories`` and the HTTP client would send ``/repositories``
    instead. The read-only endpoints accept keys created before the creation
    pattern existed, so the key must reach the server intact.
    """
    client = harness()
    client.queue_json(REPOSITORY_LIST_PAYLOAD)

    client.invoke(list_repositories, estate_key=estate_key)

    request = client.requests[0]
    encoded = "%2E" * len(estate_key)
    assert request.url.raw_path.split(b"?")[0] == (
        f"/estates/{encoded}/repositories".encode()
    )


@pytest.mark.parametrize(
    ("owner", "name"),
    [
        pytest.param(".", "..", id="dot-then-two-dots"),
        pytest.param("..", ".", id="two-dots-then-dot"),
    ],
)
def test_repo_set_encodes_dot_only_segments(
    harness: typ.Callable[..., CliHarness],
    owner: str,
    name: str,
) -> None:
    """A dot-only owner or name cannot be normalised out of the route."""
    client = harness()
    client.queue_json(TOGGLE_PAYLOAD)

    client.invoke(set_repository, owner=owner, name=name, ingestion_enabled=True)

    request = client.requests[0]
    owner_segment = "%2E" * len(owner)
    name_segment = "%2E" * len(name)
    assert request.url.raw_path == (
        f"/repositories/{owner_segment}/{name_segment}/ingestion".encode()
    )


def test_repo_list_leaves_an_ordinary_dotted_key_unchanged(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """Encoded segments contain no literal dot, so only dot-only keys change."""
    client = harness()
    client.queue_json(REPOSITORY_LIST_PAYLOAD)

    client.invoke(list_repositories, estate_key="wildside.v2")

    assert client.requests[0].url.path == "/estates/wildside.v2/repositories"


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
    error = error_document(capsys.readouterr().err)["error"]
    assert error["code"] == "dry_run_unsupported"
    assert "--dry-run" in error["hint"]


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
