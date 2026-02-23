"""Unit tests for ghillie.api.middleware.SQLAlchemySessionManager.

Usage
-----
Run with pytest::

    pytest tests/unit/test_api_middleware.py

"""

from __future__ import annotations

from http import HTTPStatus
from unittest import mock

import falcon.asgi
import falcon.testing
import pytest


class _MockSession:
    """Lightweight mock of an AsyncSession for middleware tests."""

    def __init__(self, *, is_active: bool = True) -> None:
        self.is_active = is_active
        self.commit = mock.AsyncMock()
        self.rollback = mock.AsyncMock()
        self.close = mock.AsyncMock()


class _EchoResource:
    """Resource that records whether a session was attached."""

    async def on_get(
        self, req: falcon.asgi.Request, resp: falcon.asgi.Response
    ) -> None:
        """Echo whether a session is present on the request context."""
        has_session = hasattr(req.context, "session")
        resp.media = {"has_session": has_session}
        resp.status = HTTPStatus.OK


class _ErrorResource:
    """Resource that always raises a server error."""

    async def on_get(
        self, req: falcon.asgi.Request, resp: falcon.asgi.Response
    ) -> None:
        """Raise a generic exception to trigger error handling."""
        raise falcon.HTTPInternalServerError(title="boom", description="test error")


class _BadRequestResource:
    """Resource that raises a 400 client error."""

    async def on_get(
        self, req: falcon.asgi.Request, resp: falcon.asgi.Response
    ) -> None:
        """Raise a 400 to trigger client-error handling."""
        raise falcon.HTTPBadRequest(title="bad", description="bad request")


@pytest.fixture
def session() -> _MockSession:
    """Provide a fresh mock session for each test."""
    return _MockSession()


@pytest.fixture
def client(session: _MockSession) -> falcon.testing.TestClient:
    """Build a test client with the middleware installed."""
    from ghillie.api.middleware import SQLAlchemySessionManager

    factory = mock.MagicMock(return_value=session)
    mw = SQLAlchemySessionManager(factory)
    app = falcon.asgi.App(middleware=[mw])  # type: ignore[no-matching-overload]  # Falcon stubs
    app.add_route("/echo", _EchoResource())
    app.add_route("/error", _ErrorResource())
    app.add_route("/bad-request", _BadRequestResource())
    return falcon.testing.TestClient(app)


class TestSessionAttach:
    """Middleware attaches a session to the request context."""

    def test_session_is_attached(
        self, client: falcon.testing.TestClient, session: _MockSession
    ) -> None:
        """process_request attaches a session to req.context."""
        result = client.simulate_get("/echo")
        assert result.json["has_session"] is True, "session not attached to context"

    def test_session_committed_on_success(
        self, client: falcon.testing.TestClient, session: _MockSession
    ) -> None:
        """Session is committed when the request succeeds (2xx)."""
        client.simulate_get("/echo")
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    def test_session_closed_on_success(
        self, client: falcon.testing.TestClient, session: _MockSession
    ) -> None:
        """Session is always closed, even on success."""
        client.simulate_get("/echo")
        session.close.assert_awaited_once()

    def test_session_rolled_back_on_error(
        self, client: falcon.testing.TestClient, session: _MockSession
    ) -> None:
        """Session is rolled back when a 5xx response occurs."""
        client.simulate_get("/error")
        session.rollback.assert_awaited()
        session.commit.assert_not_awaited()

    def test_session_closed_on_error(
        self, client: falcon.testing.TestClient, session: _MockSession
    ) -> None:
        """Session is closed even when the request errors."""
        client.simulate_get("/error")
        session.close.assert_awaited_once()

    def test_session_rolled_back_on_4xx(
        self, client: falcon.testing.TestClient, session: _MockSession
    ) -> None:
        """Session is rolled back when a 4xx client error occurs."""
        client.simulate_get("/bad-request")
        session.rollback.assert_awaited()
        session.commit.assert_not_awaited()

    def test_session_closed_on_4xx(
        self, client: falcon.testing.TestClient, session: _MockSession
    ) -> None:
        """Session is closed even when the request returns a 4xx."""
        client.simulate_get("/bad-request")
        session.close.assert_awaited_once()
