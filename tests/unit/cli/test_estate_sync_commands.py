"""Registry sync verb: wire contract and its removed wait option.

D2 makes sync one synchronous request, so the only options that matter are
the address it posts to, the dry-run query, and the absence of ``--wait``.
"""

from __future__ import annotations

import typing as typ

import httpx

from ghillie.cli.app import main as cli_main
from ghillie.cli.commands.estate import sync
from tests.unit.cli.harness import BASE_URL, CliHarness
from tests.unit.cli.payloads import SYNC_PAYLOAD

if typ.TYPE_CHECKING:
    import pytest


def test_sync_posts_to_the_registry_sync_endpoint(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """D2: sync is one synchronous request with no wait option."""
    client = harness()
    client.queue_json(SYNC_PAYLOAD)

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
    client.queue_json({**SYNC_PAYLOAD, "dry_run": True})

    client.invoke(sync, estate_key="demo")

    assert client.requests[0].url.params == httpx.QueryParams({"dry_run": "true"})


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
