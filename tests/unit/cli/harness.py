"""Shared harness for driving estate CLI commands against a fake control plane.

Commands obtain their client from :attr:`CommandContext.client_factory`, so the
harness supplies a factory that builds a real :class:`ControlPlaneClient` with a
:class:`httpx.MockTransport`. The client's own base URL, timeout and header
construction still run; only the transport is substituted.
"""

from __future__ import annotations

import typing as typ

import httpx

from ghillie.cli.config import ResolvedCliConfig
from ghillie.cli.context import CommandContext, use_context
from ghillie.cli.control_plane import ControlPlaneClient

BASE_URL = "http://127.0.0.1:9999"

Respond = httpx.Response | Exception


def make_config(
    *,
    output: str = "table",
    dry_run: bool = False,
    api_base_url: str = BASE_URL,
    auth_token: str | None = None,
) -> ResolvedCliConfig:
    """Build a resolved CLI configuration for one test invocation."""
    return ResolvedCliConfig(
        api_base_url=api_base_url,
        api_base_url_source="flag",
        auth_token=auth_token,
        output=typ.cast("typ.Literal['table', 'json', 'yaml']", output),
        log_level="info",
        request_timeout_s=30.0,
        non_interactive=True,
        dry_run=dry_run,
    )


class CliHarness:
    """Drive a command function with a queued fake control plane."""

    def __init__(self, config: ResolvedCliConfig | None = None) -> None:
        """Install the mock transport and fixed configuration for one test."""
        self.config = config or make_config()
        self.requests: list[httpx.Request] = []
        self._responses: list[Respond] = []
        self._transport = httpx.MockTransport(self._dispatch)

    def factory(self, config: ResolvedCliConfig) -> ControlPlaneClient:
        """Build a client whose only substitution is the mock transport."""
        return ControlPlaneClient(config, transport=self._transport)

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        """Record the request and answer it with the next queued response."""
        self.requests.append(request)
        if not self._responses:
            message = f"unexpected request: {request.method} {request.url}"
            raise AssertionError(message)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def queue_json(
        self, payload: typ.Mapping[str, object], *, status: int = 200
    ) -> None:
        """Queue a JSON response."""
        self._responses.append(httpx.Response(status, json=dict(payload)))

    def queue_raw(self, body: str, *, status: int) -> None:
        """Queue a non-JSON response."""
        self._responses.append(httpx.Response(status, text=body))

    def queue_error(self, error: Exception) -> None:
        """Queue a transport-level failure."""
        self._responses.append(error)

    def invoke(self, command: typ.Callable[..., object], **kwargs: object) -> object:
        """Run *command* with this harness's resolved configuration."""
        context = CommandContext(config=self.config, client_factory=self.factory)
        with use_context(context):
            return command(**kwargs)
