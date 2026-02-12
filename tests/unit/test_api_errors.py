"""Unit tests for ghillie.api.errors domain exceptions and error handlers.

Usage
-----
Run with pytest::

    pytest tests/unit/test_api_errors.py

"""

from __future__ import annotations

import falcon.asgi
import falcon.testing
import pytest

from ghillie.api.errors import (
    InvalidInputError,
    RepositoryNotFoundError,
    handle_invalid_input,
    handle_repository_not_found,
)


class _NotFoundResource:
    """Resource that raises RepositoryNotFoundError."""

    async def on_get(
        self, req: falcon.asgi.Request, resp: falcon.asgi.Response
    ) -> None:
        raise RepositoryNotFoundError("acme", "widgets")


class _BadRequestResource:
    """Resource that raises InvalidInputError without a field."""

    async def on_get(
        self, req: falcon.asgi.Request, resp: falcon.asgi.Response
    ) -> None:
        msg = "invalid parameter"
        raise InvalidInputError(msg)


class _BadRequestWithFieldResource:
    """Resource that raises InvalidInputError with a field."""

    async def on_get(
        self, req: falcon.asgi.Request, resp: falcon.asgi.Response
    ) -> None:
        msg = "must be positive"
        raise InvalidInputError(msg, field="count")


@pytest.fixture
def client() -> falcon.testing.TestClient:
    """Build a test client with error handlers registered."""
    app = falcon.asgi.App()
    app.add_route("/not-found", _NotFoundResource())
    app.add_route("/bad-request", _BadRequestResource())
    app.add_route("/bad-request-field", _BadRequestWithFieldResource())
    app.add_error_handler(RepositoryNotFoundError, handle_repository_not_found)
    app.add_error_handler(InvalidInputError, handle_invalid_input)
    return falcon.testing.TestClient(app)


class TestRepositoryNotFoundError:
    """Tests for RepositoryNotFoundError and its handler."""

    def test_returns_404(self, client: falcon.testing.TestClient) -> None:
        """Handler maps RepositoryNotFoundError to HTTP 404."""
        result = client.simulate_get("/not-found")
        assert result.status == falcon.HTTP_404, "expected HTTP 404"

    def test_response_body_contains_description(
        self, client: falcon.testing.TestClient
    ) -> None:
        """Response body includes the repository slug in description."""
        result = client.simulate_get("/not-found")
        assert "acme/widgets" in result.json["description"], "missing repo slug"

    def test_response_body_has_title(self, client: falcon.testing.TestClient) -> None:
        """Response body includes a title field."""
        result = client.simulate_get("/not-found")
        assert result.json["title"] == "Repository not found", "wrong title"


class TestInvalidInputHandler:
    """Tests for InvalidInputError and its handler."""

    def test_returns_400(self, client: falcon.testing.TestClient) -> None:
        """Handler maps InvalidInputError to HTTP 400."""
        result = client.simulate_get("/bad-request")
        assert result.status == falcon.HTTP_400, "expected HTTP 400"

    def test_response_body_contains_reason(
        self, client: falcon.testing.TestClient
    ) -> None:
        """Response body includes the error reason in description."""
        result = client.simulate_get("/bad-request")
        assert result.json["description"] == "invalid parameter", "wrong description"

    def test_response_body_has_title(self, client: falcon.testing.TestClient) -> None:
        """Response body includes an 'Invalid input' title."""
        result = client.simulate_get("/bad-request")
        assert result.json["title"] == "Invalid input", "wrong title"

    def test_response_omits_field_when_none(
        self, client: falcon.testing.TestClient
    ) -> None:
        """Response body excludes field key when field is None."""
        result = client.simulate_get("/bad-request")
        assert "field" not in result.json, "field should be absent"

    def test_response_includes_field_when_set(
        self, client: falcon.testing.TestClient
    ) -> None:
        """Response body includes field when provided."""
        result = client.simulate_get("/bad-request-field")
        assert result.json["field"] == "count", "wrong field value"

    def test_field_error_has_reason(self, client: falcon.testing.TestClient) -> None:
        """Response body includes the reason even with a field."""
        result = client.simulate_get("/bad-request-field")
        assert result.json["description"] == "must be positive", "wrong description"


class TestInvalidInputErrorException:
    """Tests for the InvalidInputError exception itself."""

    def test_message_without_field(self) -> None:
        """String representation is the reason when field is None."""
        ex = InvalidInputError("bad value")
        assert str(ex) == "bad value", "message should be the reason"

    def test_message_with_field(self) -> None:
        """String representation includes field prefix."""
        ex = InvalidInputError("must be positive", field="count")
        assert str(ex) == "count: must be positive", "message should include field"

    def test_reason_attribute(self) -> None:
        """Reason attribute stores the original reason."""
        ex = InvalidInputError("bad value")
        assert ex.reason == "bad value", "reason attribute mismatch"

    def test_field_attribute_none(self) -> None:
        """Field attribute defaults to None."""
        ex = InvalidInputError("bad value")
        assert ex.field is None, "field should default to None"

    def test_field_attribute_set(self) -> None:
        """Field attribute stores the provided field name."""
        ex = InvalidInputError("bad value", field="name")
        assert ex.field == "name", "field attribute mismatch"
