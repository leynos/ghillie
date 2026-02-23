"""Unit tests for the ghillie.runtime module."""

from __future__ import annotations

from http import HTTPStatus

import falcon.asgi
import falcon.testing
import pytest


@pytest.fixture
def client() -> falcon.testing.TestClient:
    """Create a test client for the Ghillie runtime app."""
    from ghillie.runtime import create_app

    return falcon.testing.TestClient(create_app())


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    def test_health_returns_200(self, client: falcon.testing.TestClient) -> None:
        """GET /health returns HTTP 200."""
        result = client.simulate_get("/health")
        assert result.status_code == HTTPStatus.OK

    def test_health_returns_json_status_ok(
        self, client: falcon.testing.TestClient
    ) -> None:
        """GET /health returns JSON with status ok."""
        result = client.simulate_get("/health")
        assert result.json == {"status": "ok"}

    def test_health_content_type_is_json(
        self, client: falcon.testing.TestClient
    ) -> None:
        """GET /health has application/json content type."""
        result = client.simulate_get("/health")
        content_type = result.headers.get("content-type", "")
        assert content_type.startswith("application/json")


class TestReadyEndpoint:
    """Tests for the /ready endpoint."""

    def test_ready_returns_200(self, client: falcon.testing.TestClient) -> None:
        """GET /ready returns HTTP 200."""
        result = client.simulate_get("/ready")
        assert result.status_code == HTTPStatus.OK

    def test_ready_returns_json_status_ready(
        self, client: falcon.testing.TestClient
    ) -> None:
        """GET /ready returns JSON with status ready."""
        result = client.simulate_get("/ready")
        assert result.json == {"status": "ready"}

    def test_ready_content_type_is_json(
        self, client: falcon.testing.TestClient
    ) -> None:
        """GET /ready has application/json content type."""
        result = client.simulate_get("/ready")
        content_type = result.headers.get("content-type", "")
        assert content_type.startswith("application/json")


class TestCreateApp:
    """Tests for the create_app factory function."""

    def test_create_app_returns_falcon_app(self) -> None:
        """create_app returns a Falcon ASGI App instance."""
        from ghillie.runtime import create_app

        app = create_app()
        assert isinstance(app, falcon.asgi.App)

    def test_app_has_health_route(self) -> None:
        """The app has a /health route."""
        from ghillie.runtime import create_app

        app = create_app()
        # Falcon apps store routes internally; test via client
        client = falcon.testing.TestClient(app)
        result = client.simulate_get("/health")
        assert result.status_code != HTTPStatus.NOT_FOUND

    def test_app_has_ready_route(self) -> None:
        """The app has a /ready route."""
        from ghillie.runtime import create_app

        app = create_app()
        client = falcon.testing.TestClient(app)
        result = client.simulate_get("/ready")
        assert result.status_code != HTTPStatus.NOT_FOUND
