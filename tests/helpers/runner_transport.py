"""Bridge the synchronous operator CLI onto the in-process ASGI app.

The CLI builds its own :class:`httpx.Client`, so behaviour tests replace the
class with a factory that adds a :class:`RunnerTransport`. The client's own
header, timeout, and base-URL construction still runs, but every request is
sent in-process to the Falcon app. The app, its SQLAlchemy engine, and its
sessions all belong to the single event loop owned by the scenario's
:class:`asyncio.Runner`, and this transport is the only place that hops onto
that loop.
"""

from __future__ import annotations

import typing as typ

import httpx

if typ.TYPE_CHECKING:
    import asyncio


class RunnerTransport(httpx.BaseTransport):
    """Forward synchronous requests to an async client on a dedicated loop.

    Parameters
    ----------
    runner
        Runner whose loop owns the application and its database sessions.
    client
        Async client bound to the in-process ASGI application.

    """

    def __init__(self, runner: asyncio.Runner, client: httpx.AsyncClient) -> None:
        """Record the loop owner and the in-process client."""
        self._runner = runner
        self._client = client
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Dispatch *request* on the runner-owned loop and wait for it.

        ``AsyncClient.send`` returns a response whose body is already read. A
        fresh synchronous response is built around that body: handing the async
        response back would make the sync client try to read a consumed stream.
        """
        self.requests.append(request)
        async_response = self._runner.run(self._client.send(request))
        return httpx.Response(
            status_code=async_response.status_code,
            headers=async_response.headers,
            content=async_response.content,
            request=request,
        )

    def close(self) -> None:
        """Leave the shared async client open; the scenario fixture closes it.

        The CLI constructs and closes one client per command. Closing the
        transport here would close the async client after the first command,
        so the fixture owns that lifetime instead.
        """
