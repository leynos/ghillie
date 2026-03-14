"""HTTP control-plane client helpers for the operator CLI."""

from __future__ import annotations

import typing as typ

import httpx

if typ.TYPE_CHECKING:
    from .config import ResolvedCliConfig


class ControlPlaneClient:
    """Thin `httpx` wrapper configured from resolved CLI settings."""

    def __init__(
        self,
        config: ResolvedCliConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Build a control-plane client from resolved CLI configuration."""
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.Client(
            base_url=config.api_base_url,
            timeout=config.request_timeout_s,
            headers=_headers_for(config),
        )

    @property
    def http_client(self) -> httpx.Client:
        """Expose the underlying `httpx.Client` for higher-level commands."""
        return self._http_client

    def close(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            self._http_client.close()

    def __enter__(self) -> ControlPlaneClient:
        """Enter a context manager scope."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Close the client when leaving a context manager scope."""
        self.close()


def _headers_for(config: ResolvedCliConfig) -> dict[str, str]:
    headers = {"User-Agent": "ghillie/0.1"}
    if config.auth_token:
        headers["Authorization"] = f"Bearer {config.auth_token}"
    return headers
