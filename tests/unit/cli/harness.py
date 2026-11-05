"""Shared harness for driving estate CLI commands against a fake control plane.

The commands build their own :class:`httpx.Client` so the real header, timeout,
and base-URL configuration is exercised. Tests therefore replace ``httpx.Client``
with a factory that injects a :class:`httpx.MockTransport`, record every request,
and queue the response (or transport exception) each test expects.
"""

from __future__ import annotations

import functools
import typing as typ

import httpx

from ghillie.cli import control_plane
from ghillie.cli.config import ResolvedCliConfig
from ghillie.cli.context import CommandContext, use_context

if typ.TYPE_CHECKING:
    import pytest

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

    # A small fixture-facing constructor is clearer than a builder object.
    def __init__(  # noqa: PLR0913
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        output: str = "table",
        dry_run: bool = False,
        api_base_url: str = BASE_URL,
        auth_token: str | None = None,
    ) -> None:
        """Install the fake transport and fixed configuration for one test."""
        self.config = make_config(
            output=output,
            dry_run=dry_run,
            api_base_url=api_base_url,
            auth_token=auth_token,
        )
        self.requests: list[httpx.Request] = []
        self._responses: list[Respond] = []
        self._transport = httpx.MockTransport(self._dispatch)
        # Bind the transport ahead of the command's own base URL, timeout and
        # header arguments, so the real client configuration is still exercised.
        real_client = httpx.Client
        monkeypatch.setattr(
            control_plane.httpx,
            "Client",
            functools.partial(real_client, transport=self._transport),
        )

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
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
        with use_context(CommandContext(config=self.config)):
            return command(**kwargs)
