"""Unit tests for ghillie.api.app application factory."""

from __future__ import annotations

from unittest import mock

import falcon.asgi
import falcon.testing

from ghillie.api.app import AppDependencies, create_app


def _mock_deps() -> AppDependencies:
    """Build AppDependencies with mock objects.

    The session factory must return an object with the async methods
    the middleware expects (commit, rollback, close, is_active).
    """
    mock_session = mock.MagicMock()
    mock_session.is_active = True
    mock_session.commit = mock.AsyncMock()
    mock_session.rollback = mock.AsyncMock()
    mock_session.close = mock.AsyncMock()

    session_factory = mock.MagicMock(return_value=mock_session)
    reporting_service = mock.MagicMock()
    return AppDependencies(
        session_factory=session_factory,
        reporting_service=reporting_service,
    )


class TestCreateAppHealthOnly:
    """Tests for create_app() without domain dependencies."""

    def test_returns_falcon_app(self) -> None:
        """create_app() returns a Falcon ASGI App."""
        app = create_app()
        assert isinstance(app, falcon.asgi.App)

    def test_has_health_route(self) -> None:
        """Health-only app responds to /health."""
        client = falcon.testing.TestClient(create_app())
        result = client.simulate_get("/health")
        assert result.status == falcon.HTTP_200
        assert result.json == {"status": "ok"}

    def test_has_ready_route(self) -> None:
        """Health-only app responds to /ready."""
        client = falcon.testing.TestClient(create_app())
        result = client.simulate_get("/ready")
        assert result.status == falcon.HTTP_200
        assert result.json == {"status": "ready"}

    def test_report_endpoint_not_registered(self) -> None:
        """Without deps, report endpoint returns 404."""
        client = falcon.testing.TestClient(create_app())
        result = client.simulate_post("/reports/repositories/acme/widgets")
        assert result.status == falcon.HTTP_404


class TestCreateAppWithDeps:
    """Tests for create_app() with full domain dependencies."""

    def test_returns_falcon_app(self) -> None:
        """create_app(deps) returns a Falcon ASGI App."""
        app = create_app(_mock_deps())
        assert isinstance(app, falcon.asgi.App)

    def test_has_health_route(self) -> None:
        """Full app still responds to /health."""
        client = falcon.testing.TestClient(create_app(_mock_deps()))
        result = client.simulate_get("/health")
        assert result.status == falcon.HTTP_200

    def test_has_ready_route(self) -> None:
        """Full app still responds to /ready."""
        client = falcon.testing.TestClient(create_app(_mock_deps()))
        result = client.simulate_get("/ready")
        assert result.status == falcon.HTTP_200

    def test_report_endpoint_registered(self) -> None:
        """With deps, report endpoint is registered (not 404)."""
        client = falcon.testing.TestClient(create_app(_mock_deps()))
        result = client.simulate_post("/reports/repositories/acme/widgets")
        # The route exists but the mock won't work; we just verify it's not 404
        assert result.status != falcon.HTTP_404
