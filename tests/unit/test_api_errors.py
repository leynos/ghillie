"""Unit tests for ghillie.api.errors domain exceptions and error handlers."""

from __future__ import annotations

import falcon.asgi
import falcon.testing

from ghillie.api.errors import (
    RepositoryNotFoundError,
    handle_repository_not_found,
    handle_value_error,
)


def _build_app() -> falcon.testing.TestClient:
    """Build a test client with error handlers registered."""

    class _NotFoundResource:
        async def on_get(
            self, req: falcon.asgi.Request, resp: falcon.asgi.Response
        ) -> None:
            raise RepositoryNotFoundError("acme", "widgets")

    class _BadRequestResource:
        async def on_get(
            self, req: falcon.asgi.Request, resp: falcon.asgi.Response
        ) -> None:
            msg = "invalid parameter"
            raise ValueError(msg)

    app = falcon.asgi.App()
    app.add_route("/not-found", _NotFoundResource())
    app.add_route("/bad-request", _BadRequestResource())
    app.add_error_handler(RepositoryNotFoundError, handle_repository_not_found)
    app.add_error_handler(ValueError, handle_value_error)
    return falcon.testing.TestClient(app)


class TestRepositoryNotFoundError:
    """Tests for RepositoryNotFoundError and its handler."""

    def test_returns_404(self) -> None:
        """Handler maps RepositoryNotFoundError to HTTP 404."""
        client = _build_app()
        result = client.simulate_get("/not-found")
        assert result.status == falcon.HTTP_404

    def test_response_body_contains_description(self) -> None:
        """Response body includes the repository slug in description."""
        client = _build_app()
        result = client.simulate_get("/not-found")
        assert "acme/widgets" in result.json["description"]

    def test_response_body_has_title(self) -> None:
        """Response body includes a title field."""
        client = _build_app()
        result = client.simulate_get("/not-found")
        assert result.json["title"] == "Repository not found"


class TestValueErrorHandler:
    """Tests for the ValueError handler."""

    def test_returns_400(self) -> None:
        """Handler maps ValueError to HTTP 400."""
        client = _build_app()
        result = client.simulate_get("/bad-request")
        assert result.status == falcon.HTTP_400

    def test_response_body_contains_message(self) -> None:
        """Response body includes the error message."""
        client = _build_app()
        result = client.simulate_get("/bad-request")
        assert "invalid parameter" in result.json["description"]
