"""Unit tests for ghillie.api.app application factory.

Usage
-----
Run with pytest::

    pytest tests/unit/test_api_app.py

"""

from http import HTTPStatus
from unittest import mock

import falcon.asgi
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


class _EmptyEstateService:
    """Estate port double that returns an empty first page."""

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


@pytest.fixture
def deps() -> AppDependencies:
    """Build AppDependencies with mock objects."""
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


@pytest.fixture
def health_client() -> falcon.testing.TestClient:
    """Build a test client for health-only mode."""
    return falcon.testing.TestClient(create_app())


@pytest.fixture
def full_client(deps: AppDependencies) -> falcon.testing.TestClient:
    """Build a test client with full domain dependencies."""
    return falcon.testing.TestClient(create_app(deps))


class TestCreateAppHealthOnly:
    """Tests for create_app() without domain dependencies."""

    def test_returns_falcon_app(self) -> None:
        """Create_app() returns a Falcon ASGI App."""
        app = create_app()
        assert isinstance(app, falcon.asgi.App), "expected Falcon ASGI App"

    def test_has_health_route(self, health_client: falcon.testing.TestClient) -> None:
        """Health-only app responds to /health."""
        result = health_client.simulate_get("/health")
        assert result.status_code == HTTPStatus.OK, "expected HTTP 200 from /health"
        assert result.json == {"status": "ok"}, "wrong /health body"

    def test_has_ready_route(self, health_client: falcon.testing.TestClient) -> None:
        """Health-only app responds to /ready."""
        result = health_client.simulate_get("/ready")
        assert result.status_code == HTTPStatus.OK, "expected HTTP 200 from /ready"
        assert result.json == {"status": "ready"}, "wrong /ready body"

    def test_report_endpoint_not_registered(
        self, health_client: falcon.testing.TestClient
    ) -> None:
        """Without deps, report endpoint returns 404."""
        result = health_client.simulate_post("/reports/repositories/acme/widgets")
        assert result.status_code == HTTPStatus.NOT_FOUND, "expected HTTP 404"


class TestCreateAppWithDeps:
    """Tests for create_app() with full domain dependencies."""

    def test_returns_falcon_app(self, deps: AppDependencies) -> None:
        """Create_app(deps) returns a Falcon ASGI App."""
        app = create_app(deps)
        assert isinstance(app, falcon.asgi.App), "expected Falcon ASGI App"

    def test_has_health_route(self, full_client: falcon.testing.TestClient) -> None:
        """Full app still responds to /health."""
        result = full_client.simulate_get("/health")
        assert result.status_code == HTTPStatus.OK, "expected HTTP 200 from /health"

    def test_has_ready_route(self, full_client: falcon.testing.TestClient) -> None:
        """Full app still responds to /ready."""
        result = full_client.simulate_get("/ready")
        assert result.status_code == HTTPStatus.OK, "expected HTTP 200 from /ready"

    def test_report_endpoint_registered(
        self, full_client: falcon.testing.TestClient
    ) -> None:
        """With deps, report endpoint is registered (not 404)."""
        result = full_client.simulate_post("/reports/repositories/acme/widgets")
        assert result.status_code != HTTPStatus.NOT_FOUND, "route should be registered"


class TestCreateAppEstateRoutes:
    """Route families vary independently with their dependencies."""

    def test_estate_only_app_registers_estate_routes(self) -> None:
        """An estate service alone exposes the estate family."""
        client = falcon.testing.TestClient(
            create_app(AppDependencies(estate_service=_EmptyEstateService()))
        )

        assert client.simulate_get("/estates").status_code == HTTPStatus.OK
        assert (
            client.simulate_post("/reports/repositories/acme/widgets").status_code
            == HTTPStatus.NOT_FOUND
        )

    def test_reporting_only_app_does_not_register_estate_routes(
        self, deps: AppDependencies
    ) -> None:
        """Reporting dependencies alone do not expose the estate family."""
        client = falcon.testing.TestClient(create_app(deps))

        assert client.simulate_get("/estates").status_code == HTTPStatus.NOT_FOUND
        assert (
            client.simulate_post("/reports/repositories/acme/widgets").status_code
            != HTTPStatus.NOT_FOUND
        )

    def test_both_dependency_families_are_registered(
        self, deps: AppDependencies
    ) -> None:
        """Supplying both services exposes both route families."""
        client = falcon.testing.TestClient(
            create_app(
                AppDependencies(
                    session_factory=deps.session_factory,
                    reporting_service=deps.reporting_service,
                    estate_service=_EmptyEstateService(),
                )
            )
        )

        assert client.simulate_get("/estates").status_code == HTTPStatus.OK
        assert (
            client.simulate_post("/reports/repositories/acme/widgets").status_code
            != HTTPStatus.NOT_FOUND
        )

    def test_no_dependencies_registers_no_domain_routes(self) -> None:
        """A dependency-free app keeps only the probes."""
        client = falcon.testing.TestClient(create_app())

        assert client.simulate_get("/estates").status_code == HTTPStatus.NOT_FOUND
        assert (
            client.simulate_post("/reports/repositories/acme/widgets").status_code
            == HTTPStatus.NOT_FOUND
        )
