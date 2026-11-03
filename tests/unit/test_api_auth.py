"""Optional bearer-token authentication for the HTTP API (D14).

When ``GHILLIE_API_TOKEN`` is configured, every route except ``/health`` and
``/ready`` requires ``Authorization: Bearer <token>``. When it is not, the API
stays unauthenticated.
"""

import falcon.testing
import pytest

from ghillie.api.app import AppDependencies, create_app
from ghillie.estate.models import (
    CatalogueImportSummary,
    EstateSummary,
    IngestionToggleOutcome,
    Page,
    PageRequest,
    RegistrySyncSummary,
    RepositoryPage,
    RepositoryQuery,
)

_TOKEN = "s3cret-token-value"  # noqa: S105 - test credential, not a secret.
_AUTHORIZATION = "Authorization"


class _EmptyEstateManagement:
    """Minimal port double used only to register the estate routes."""

    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]:
        """Return an empty page."""
        return Page(
            items=(),
            limit=page.limit,
            offset=page.offset,
            has_more=False,
            next_offset=None,
        )

    async def import_catalogue(  # noqa: PLR0913 - mirrors the port signature.
        self,
        estate_key: str,
        *,
        catalogue_yaml: str,
        commit_sha: str,
        estate_name: str | None,
        dry_run: bool,
    ) -> CatalogueImportSummary:
        """Not exercised by these tests."""
        raise NotImplementedError

    async def sync_registry(
        self, estate_key: str, *, dry_run: bool
    ) -> RegistrySyncSummary:
        """Not exercised by these tests."""
        raise NotImplementedError

    async def list_repositories(
        self, estate_key: str, query: RepositoryQuery
    ) -> RepositoryPage:
        """Not exercised by these tests."""
        raise NotImplementedError

    async def set_ingestion(
        self, owner: str, name: str, *, enabled: bool
    ) -> IngestionToggleOutcome:
        """Not exercised by these tests."""
        raise NotImplementedError


def _client(*, token: str | None) -> falcon.testing.TestClient:
    """Build a client with the estate routes registered."""
    return falcon.testing.TestClient(
        create_app(
            AppDependencies(
                estate_service=_EmptyEstateManagement(),
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

        assert result.status_code == 401
        assert result.json["code"] == "unauthorized"
        assert result.headers.get("WWW-Authenticate") == "Bearer"

    def test_wrong_token_is_unauthorized(
        self, client: falcon.testing.TestClient
    ) -> None:
        """A wrong token is a 401 and never echoes the token."""
        result = client.simulate_get(
            "/estates", headers={_AUTHORIZATION: "Bearer wrong-token"}
        )

        assert result.status_code == 401
        assert result.json["code"] == "unauthorized"
        assert "wrong-token" not in result.text
        assert _TOKEN not in result.text

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

        assert result.status_code == 401
        assert result.json["code"] == "unauthorized"

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

        assert result.status_code == 200
        assert result.json["items"] == []

    @pytest.mark.parametrize("path", ["/health", "/ready"])
    def test_health_and_readiness_are_exempt(
        self, client: falcon.testing.TestClient, path: str
    ) -> None:
        """Probes work without a token so Kubernetes can reach them."""
        result = client.simulate_get(path)

        assert result.status_code == 200

    def test_unknown_path_still_requires_a_token(
        self, client: falcon.testing.TestClient
    ) -> None:
        """Authentication is enforced before routing."""
        result = client.simulate_get("/nope")

        assert result.status_code == 401
        assert result.json["code"] == "unauthorized"

    def test_unauthorized_response_does_not_echo_the_configured_token(
        self, client: falcon.testing.TestClient
    ) -> None:
        """The token is never included in an error response."""
        result = client.simulate_get("/estates")

        assert _TOKEN not in result.text


class TestNoTokenConfigured:
    """Behaviour when authentication is disabled."""

    def test_estate_route_is_open(self) -> None:
        """Without a token the API stays unauthenticated."""
        result = _client(token=None).simulate_get("/estates")

        assert result.status_code == 200

    def test_empty_token_is_treated_as_unconfigured(self) -> None:
        """An empty environment value does not enable authentication."""
        result = _client(token="").simulate_get("/estates")

        assert result.status_code == 200
