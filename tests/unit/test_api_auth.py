"""Optional bearer-token authentication for the HTTP API (D14).

When ``GHILLIE_API_TOKEN`` is configured, every route except ``/health`` and
``/ready`` requires ``Authorization: Bearer <token>``. When it is not, the API
stays unauthenticated.
"""

import falcon.testing
import pytest

from ghillie.api.app import AppDependencies, _build_middleware, create_app
from ghillie.api.auth import BearerTokenMiddleware
from tests.unit.estate_test_helpers import EmptyEstateManagement

_TOKEN = "s3cret-token-value"  # noqa: S105 - test credential, not a secret.
_AUTHORIZATION = "Authorization"


def _client(*, token: str | None) -> falcon.testing.TestClient:
    """Build a client with the estate routes registered."""
    return falcon.testing.TestClient(
        create_app(
            AppDependencies(
                estate_service=EmptyEstateManagement(),
                api_token=token,
            )
        )
    )


@pytest.fixture
def client() -> falcon.testing.TestClient:
    """Build an authenticated client."""
    return _client(token=_TOKEN)


class TestTokenConfigured:
    """Behaviour when a token is configured."""

    def test_missing_header_is_unauthorized(
        self, client: falcon.testing.TestClient
    ) -> None:
        """A protected route without a header is a structured 401."""
        result = client.simulate_get("/estates")

        assert result.status_code == 401, "missing header should be unauthorised"
        assert result.json["code"] == "unauthorized", "code should be unauthorised"
        assert result.headers.get("WWW-Authenticate") == "Bearer", "challenge is bearer"

    def test_wrong_token_is_unauthorized(
        self, client: falcon.testing.TestClient
    ) -> None:
        """A wrong token is a 401 and never echoes the token."""
        result = client.simulate_get(
            "/estates", headers={_AUTHORIZATION: "Bearer wrong-token"}
        )

        assert result.status_code == 401, "wrong token should be unauthorised"
        assert result.json["code"] == "unauthorized", "code should be unauthorised"
        assert "wrong-token" not in result.text, "response should not echo the token"
        assert _TOKEN not in result.text, "response should never echo the token"

    @pytest.mark.parametrize(
        "header",
        [
            "",
            "Bearer",
            "Bearer ",
            "Basic s3cret-token-value",
            "s3cret-token-value",
        ],
    )
    def test_malformed_header_is_unauthorized(
        self, client: falcon.testing.TestClient, header: str
    ) -> None:
        """Anything that is not a non-empty bearer credential is rejected."""
        result = client.simulate_get("/estates", headers={_AUTHORIZATION: header})

        assert result.status_code == 401, "malformed header should be unauthorised"
        assert result.json["code"] == "unauthorized", "code should be unauthorised"

    @pytest.mark.parametrize(
        "header",
        [
            f"Bearer {_TOKEN}",
            f"bearer {_TOKEN}",
            f"BEARER {_TOKEN}",
        ],
    )
    def test_correct_token_is_accepted(
        self, client: falcon.testing.TestClient, header: str
    ) -> None:
        """The scheme is case-insensitive, as HTTP requires."""
        result = client.simulate_get("/estates", headers={_AUTHORIZATION: header})

        assert result.status_code == 200, "valid token should be accepted"
        assert result.json["items"] == [], "listing should start empty"

    @pytest.mark.parametrize("path", ["/health", "/ready"])
    def test_health_and_readiness_are_exempt(
        self, client: falcon.testing.TestClient, path: str
    ) -> None:
        """Probes work without a token so Kubernetes can reach them."""
        result = client.simulate_get(path)

        assert result.status_code == 200, "probe should succeed without a token"

    def test_non_ascii_credential_is_unauthorized(
        self, client: falcon.testing.TestClient
    ) -> None:
        """A Latin-1 credential is a 401, not a comparison error."""
        result = client.simulate_get(
            "/estates", headers={_AUTHORIZATION: "Bearer café"}
        )

        assert result.status_code == 401, "non-ascii credential should be unauthorised"
        assert result.json["code"] == "unauthorized", "code should be unauthorised"

    def test_unknown_path_still_requires_a_token(
        self, client: falcon.testing.TestClient
    ) -> None:
        """Authentication is enforced before routing."""
        result = client.simulate_get("/nope")

        assert result.status_code == 401, "unknown path should still need a token"
        assert result.json["code"] == "unauthorized", "code should be unauthorised"

    def test_unauthorized_response_does_not_echo_the_configured_token(
        self, client: falcon.testing.TestClient
    ) -> None:
        """The token is never included in an error response."""
        result = client.simulate_get("/estates")

        assert _TOKEN not in result.text, "response should never echo the token"


class TestNoTokenConfigured:
    """Behaviour when authentication is disabled."""

    def test_estate_route_is_open(self) -> None:
        """Without a token the API stays unauthenticated."""
        result = _client(token=None).simulate_get("/estates")

        assert result.status_code == 200, "estate route should be open"

    def test_empty_token_is_treated_as_unconfigured(self) -> None:
        """An empty environment value does not enable authentication."""
        result = _client(token="").simulate_get("/estates")

        assert result.status_code == 200, "empty token should disable auth"


def _has_bearer_middleware(deps: AppDependencies) -> bool:
    """Return whether the assembled stack contains the bearer middleware."""
    return any(
        isinstance(item, BearerTokenMiddleware) for item in _build_middleware(deps)
    )


def test_estate_routes_install_middleware_without_a_token() -> None:
    """The middleware is built even when auth is off, so it can warn."""
    deps = AppDependencies(estate_service=EmptyEstateManagement())

    assert _has_bearer_middleware(deps), (
        "estate routes should install the bearer middleware to log disabled auth"
    )


def test_token_middleware_is_installed_without_estate_routes() -> None:
    """A configured token still protects a reports-only app."""
    deps = AppDependencies(api_token=_TOKEN)

    assert _has_bearer_middleware(deps), (
        "a configured token should install the middleware for every route family"
    )
