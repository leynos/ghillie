"""Estate list verb: an unfiltered collection and its table rendering.

D4 removed estate lifecycle state, so "list" is a plain GET and the removed
``--active/--inactive`` options must be rejected rather than ignored.
"""

from __future__ import annotations

import typing as typ

import httpx
import pytest

from ghillie.cli.app import main as cli_main
from ghillie.cli.commands.estate import list_estates
from tests.unit.cli.harness import BASE_URL, CliHarness
from tests.unit.cli.payloads import ESTATE_LIST_PAYLOAD


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

    result = cli_main(
        ["--api-base-url", BASE_URL, "estate", "list", "--active"],
        client_factory=client.factory,
    )

    assert result == 2
    assert client.requests == [], "no request may be sent"
    assert capsys.readouterr().err


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"items": [None]}, id="non-object-item"),
        pytest.param({"items": "not-a-list"}, id="items-not-a-list"),
        pytest.param({}, id="items-missing"),
    ],
)
def test_estate_list_rejects_a_malformed_page(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
    payload: dict[str, object],
) -> None:
    """A 200 that is not a page is a malformed response, not an empty success.

    ``render_collection`` expects mappings, so an unchecked cast turns
    ``{"items": [null]}`` into a ``TypeError`` outside the error handler, and a
    missing or non-list ``items`` into a false empty page.
    """
    client = harness()

    client.queue_json(payload)
    result = client.invoke(list_estates)

    assert result == 3
    captured = capsys.readouterr()
    assert "invalid_response" in captured.err


def test_estate_list_renders_an_empty_page_as_a_success(
    harness: typ.Callable[..., CliHarness],
) -> None:
    """An empty ``items`` list is a valid page, not a malformed response.

    The success control for the malformed-page cases: the same validation
    must let an empty collection through and keep the pagination metadata.
    """
    client = harness()
    client.queue_json(
        {
            "items": [],
            "limit": 50,
            "offset": 0,
            "has_more": False,
            "next_offset": None,
        }
    )

    result = typ.cast("str", client.invoke(list_estates))

    lines = result.splitlines()
    assert "KEY" in lines[0], "the header should still render"
    assert any("has_more=false" in line for line in lines), (
        "the empty page should keep its pagination metadata"
    )


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
