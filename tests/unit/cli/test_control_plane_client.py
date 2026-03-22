"""Unit tests for the CLI control-plane client wrapper."""

from __future__ import annotations

import httpx

from ghillie.cli.config import ResolvedCliConfig
from ghillie.cli.control_plane import ControlPlaneClient


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
