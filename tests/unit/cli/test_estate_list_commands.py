"""Estate list verb: an unfiltered collection and its table rendering.

D4 removed estate lifecycle state, so "list" is a plain GET and the removed
``--active/--inactive`` options must be rejected rather than ignored.
"""

from __future__ import annotations

import typing as typ

import httpx

from ghillie.cli.app import main as cli_main
from ghillie.cli.commands.estate import list_estates
from tests.unit.cli.harness import BASE_URL, CliHarness
from tests.unit.cli.payloads import ESTATE_LIST_PAYLOAD

if typ.TYPE_CHECKING:
    import pytest


def test_estate_list_gets_the_collection_without_filters(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """D4: estates have no lifecycle state, so the request carries no filter."""
    client = harness()
    client.queue_json(ESTATE_LIST_PAYLOAD)

    result = client.invoke(list_estates)

    assert isinstance(result, str)
    request = client.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/estates"
    assert request.url.params == httpx.QueryParams()


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


def test_estate_list_table_names_each_estate(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """The table output is readable: a header plus one row per estate."""
    client = harness()
    client.queue_json(ESTATE_LIST_PAYLOAD)

    result = typ.cast("str", client.invoke(list_estates))

    lines = result.splitlines()
    assert "KEY" in lines[0]
    assert "NAME" in lines[0]
    assert any("demo" in line and "Demo Estate" in line for line in lines)
    assert any("has_more=false" in line for line in lines)
