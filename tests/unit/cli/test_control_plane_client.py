"""Unit tests for the CLI control-plane client wrapper."""

from __future__ import annotations

import urllib.parse

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from ghillie.cli.config import ResolvedCliConfig
from ghillie.cli.control_plane import ControlPlaneClient, _quote_path


@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        pytest.param(
            ("estates", "demo", "repositories"),
            "/estates/demo/repositories",
            id="ordinary",
        ),
        pytest.param(
            ("estates", "..", "repositories"),
            "/estates/%2E%2E/repositories",
            id="two-dots",
        ),
        pytest.param(
            ("estates", ".", "repositories"), "/estates/%2E/repositories", id="dot"
        ),
        pytest.param(("a b", "c/d"), "/a%20b/c%2Fd", id="reserved-characters"),
        pytest.param(("wildside.v2",), "/wildside.v2", id="ordinary-dotted"),
    ],
)
def test_quote_path_keeps_each_segment_in_place(
    segments: tuple[str, ...],
    expected: str,
) -> None:
    """A segment can neither become a relative-path marker nor change the route.

    ``quote(..., safe="")`` leaves dots alone, so a segment made up only of
    dots needs encoding; an ordinary dotted segment must stay readable.
    """
    assert _quote_path(segments) == expected


_PATH_SEGMENT = st.one_of(
    st.text(
        max_size=32,
        # A lone surrogate cannot survive UTF-8 encoding, so no argv can carry one.
        alphabet=st.characters(blacklist_categories=("Cs",)),
    ),
    # Uniform text almost never draws a dot-only segment, so draw that shape
    # directly; it is the case the encoding exists for.
    st.text(alphabet=".", min_size=1, max_size=6),
    st.sampled_from(["..", "./..", "...", "%2E", "a/b", "a b", "", "wildside.v2"]),
)


@given(segments=st.lists(_PATH_SEGMENT, min_size=1, max_size=4))
def test_property_quote_path_cannot_change_the_route(
    segments: list[str],
) -> None:
    """Invariant: quoting preserves each segment and confines it to one place.

    A segment reaches the server in the same position it left in, so no value
    can address a different resource. Three consequences follow, and each is
    checked separately because they fail for different reasons: decoding
    restores the original, no raw ``/`` survives to split the path, and no
    encoded segment can be read as a relative-path marker.
    """
    quoted = _quote_path(segments)
    encoded = quoted.split("/")[1:]

    assert len(encoded) == len(segments), quoted
    for original, segment in zip(segments, encoded, strict=True):
        assert "/" not in segment, quoted
        assert not (segment and set(segment) == {"."}), quoted
        assert urllib.parse.unquote(segment) == original, quoted


@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        pytest.param([], "/", id="no-segments"),
        pytest.param([""], "/", id="one-empty-segment"),
        pytest.param(["", ""], "//", id="two-empty-segments"),
    ],
)
def test_quote_path_keeps_empty_segments_empty(
    segments: list[str],
    expected: str,
) -> None:
    """An empty segment adds no character, so the path gains no new component."""
    assert _quote_path(segments) == expected


def test_control_plane_client_uses_base_url_timeout_and_auth_header() -> None:
    """The HTTP client wrapper should reflect the resolved CLI configuration."""
    client = ControlPlaneClient(
        ResolvedCliConfig(
            api_base_url="http://127.0.0.1:9999",
            api_base_url_source="flag",
            auth_token="secret-token",  # noqa: S106
            output="table",
            log_level="info",
            request_timeout_s=12.5,
            non_interactive=True,
            dry_run=False,
        )
    )

    try:
        assert client.http_client.base_url == httpx.URL("http://127.0.0.1:9999")
        assert client.http_client.timeout == httpx.Timeout(12.5)
        assert client.http_client.headers["Authorization"] == "Bearer secret-token"
    finally:
        client.close()


def test_control_plane_client_closes_owned_http_client() -> None:
    """Closing the wrapper should close the owned `httpx.Client` instance."""
    client = ControlPlaneClient(
        ResolvedCliConfig(
            api_base_url="http://127.0.0.1:9999",
            api_base_url_source="fallback",
            auth_token=None,
            output="table",
            log_level="info",
            request_timeout_s=30.0,
            non_interactive=True,
            dry_run=False,
        )
    )

    client.close()

    assert client.http_client.is_closed is True


def test_control_plane_client_does_not_send_auth_header_when_token_is_none() -> None:
    """If auth_token is None, the client should not send an Authorization header."""
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Capture the request headers and return an OK response."""
        nonlocal captured_headers
        captured_headers = dict(request.headers)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    external_client = httpx.Client(
        base_url="http://127.0.0.1:9999", transport=transport
    )

    config = ResolvedCliConfig(
        api_base_url="http://127.0.0.1:9999",
        api_base_url_source="flag",
        auth_token=None,
        output="table",
        log_level="info",
        request_timeout_s=5.0,
        non_interactive=True,
        dry_run=False,
    )

    with ControlPlaneClient(config, http_client=external_client) as client:
        # Perform any request so we can inspect the headers used.
        client.http_client.get("/ping")

    # httpx normalizes header names; use case-insensitive lookup.
    assert "authorization" not in {k.lower(): v for k, v in captured_headers.items()}


def test_control_plane_client_context_manager_closes_on_exit() -> None:
    """The client should always be closed when leaving a context manager."""
    config = ResolvedCliConfig(
        api_base_url="http://127.0.0.1:9999",
        api_base_url_source="flag",
        auth_token="secret-token",  # noqa: S106
        output="table",
        log_level="info",
        request_timeout_s=5.0,
        non_interactive=True,
        dry_run=False,
    )

    with ControlPlaneClient(config) as client:
        underlying = client.http_client
        assert isinstance(underlying, httpx.Client)
        assert not underlying.is_closed

    # After the context, the underlying client should be closed.
    assert underlying.is_closed


def test_control_plane_client_context_manager_closes_on_exception() -> None:
    """The client should close even if an exception is raised."""
    config = ResolvedCliConfig(
        api_base_url="http://127.0.0.1:9999",
        api_base_url_source="flag",
        auth_token="secret-token",  # noqa: S106
        output="table",
        log_level="info",
        request_timeout_s=5.0,
        non_interactive=True,
        dry_run=False,
    )

    def _raise_in_context(client: ControlPlaneClient) -> None:
        """Raise a RuntimeError to exercise context-manager cleanup."""
        raise RuntimeError("boom")

    try:
        with ControlPlaneClient(config) as client:
            underlying = client.http_client
            _raise_in_context(client)
    except RuntimeError:
        pass

    assert underlying.is_closed


def test_control_plane_client_does_not_close_external_client() -> None:
    """When constructed with an external httpx.Client, close() must not close it."""
    config = ResolvedCliConfig(
        api_base_url="http://127.0.0.1:9999",
        api_base_url_source="flag",
        auth_token="secret-token",  # noqa: S106
        output="table",
        log_level="info",
        request_timeout_s=5.0,
        non_interactive=True,
        dry_run=False,
    )

    external_client = httpx.Client(base_url="http://127.0.0.1:9999")

    control_plane_client = ControlPlaneClient(config, http_client=external_client)
    control_plane_client.close()

    # The wrapper should respect ownership and not close non-owned clients.
    assert not external_client.is_closed
    external_client.close()
