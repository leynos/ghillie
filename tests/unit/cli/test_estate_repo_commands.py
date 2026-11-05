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

from ghillie.cli.app import main as cli_main
from ghillie.cli.commands.estate import list_repositories, set_repository
from tests.unit.cli.harness import BASE_URL, CliHarness
from tests.unit.cli.payloads import (
    REPOSITORY_LIST_PAYLOAD,
    TOGGLE_PAYLOAD,
    error_document,
)

if typ.TYPE_CHECKING:
    import pytest


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

    assert client.requests == [], "no request may be sent"
    captured = capsys.readouterr()
    assert captured.out == "", "validation errors go to standard error"
    assert captured.err


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
