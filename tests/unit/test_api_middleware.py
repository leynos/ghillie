"""Unit tests for ghillie.api.middleware.SQLAlchemySessionManager."""

from __future__ import annotations

from unittest import mock

import falcon.asgi
import falcon.testing


class _MockSession:
    """Lightweight mock of an AsyncSession for middleware tests."""

    def __init__(self, *, is_active: bool = True) -> None:
        self.is_active = is_active
        self.commit = mock.AsyncMock()
        self.rollback = mock.AsyncMock()
        self.close = mock.AsyncMock()


def _make_factory(session: _MockSession) -> mock.MagicMock:
    """Return a callable that behaves like an async_sessionmaker."""
    factory = mock.MagicMock()
    factory.return_value = session
    return factory


class _EchoResource:
    """Resource that records whether a session was attached."""

    async def on_get(
        self, req: falcon.asgi.Request, resp: falcon.asgi.Response
    ) -> None:
        """Echo whether a session is present on the request context."""
        has_session = hasattr(req.context, "session")
        resp.media = {"has_session": has_session}
        resp.status = falcon.HTTP_200


class _ErrorResource:
    """Resource that always raises a server error."""

    async def on_get(
        self, req: falcon.asgi.Request, resp: falcon.asgi.Response
    ) -> None:
        """Raise a generic exception to trigger error handling."""
        raise falcon.HTTPInternalServerError(title="boom", description="test error")


def _build_app(
    session: _MockSession,
) -> tuple[falcon.testing.TestClient, _MockSession]:
    """Build a test client with the middleware installed."""
    from ghillie.api.middleware import SQLAlchemySessionManager

    factory = _make_factory(session)
    mw = SQLAlchemySessionManager(factory)
    app = falcon.asgi.App(middleware=[mw])  # type: ignore[no-matching-overload]  # Falcon stubs
    app.add_route("/echo", _EchoResource())
    app.add_route("/error", _ErrorResource())
    return falcon.testing.TestClient(app), session


class TestSessionAttach:
    """Middleware attaches a session to the request context."""

    def test_session_is_attached(self) -> None:
        """process_request attaches a session to req.context."""
        session = _MockSession()
        client, _ = _build_app(session)
        result = client.simulate_get("/echo")
        assert result.json["has_session"] is True

    def test_session_committed_on_success(self) -> None:
        """Session is committed when the request succeeds (2xx)."""
        session = _MockSession()
        client, _ = _build_app(session)
        client.simulate_get("/echo")
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    def test_session_closed_on_success(self) -> None:
        """Session is always closed, even on success."""
        session = _MockSession()
        client, _ = _build_app(session)
        client.simulate_get("/echo")
        session.close.assert_awaited_once()

    def test_session_rolled_back_on_error(self) -> None:
        """Session is rolled back when a 5xx response occurs."""
        session = _MockSession()
        client, _ = _build_app(session)
        client.simulate_get("/error")
        session.rollback.assert_awaited()
        session.commit.assert_not_awaited()

    def test_session_closed_on_error(self) -> None:
        """Session is closed even when the request errors."""
        session = _MockSession()
        client, _ = _build_app(session)
        client.simulate_get("/error")
        session.close.assert_awaited_once()
