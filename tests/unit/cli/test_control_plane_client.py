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
