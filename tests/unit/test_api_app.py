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
from tests.unit.estate_test_helpers import EmptyEstateManagement


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


def test_app_dependencies_repr_does_not_expose_the_token() -> None:
    """A token must not leak through a repr, log line, or traceback."""
    deps = AppDependencies(
        estate_service=EmptyEstateManagement(),
        api_token="s3cret-token-value",  # noqa: S106 - test credential.
    )

    assert "s3cret-token-value" not in repr(deps), "repr must not expose the token"


class TestCreateAppEstateRoutes:
    """Route families vary independently with their dependencies."""

    @pytest.mark.parametrize(
        "case",
        [
            pytest.param((True, False, HTTPStatus.OK, False), id="estate-only"),
            pytest.param(
                (False, True, HTTPStatus.NOT_FOUND, True), id="reporting-only"
            ),
            pytest.param((True, True, HTTPStatus.OK, True), id="both"),
            pytest.param((False, False, HTTPStatus.NOT_FOUND, False), id="neither"),
        ],
    )
    def test_route_families_follow_their_dependencies(
        self,
        deps: AppDependencies,
        case: tuple[bool, bool, HTTPStatus, bool],
    ) -> None:
        """Each route family appears only when its dependencies are supplied."""
        has_estate, has_reporting, estate_status, has_report_route = case
        client = falcon.testing.TestClient(
            create_app(
                AppDependencies(
                    session_factory=deps.session_factory if has_reporting else None,
                    reporting_service=(
                        deps.reporting_service if has_reporting else None
                    ),
                    estate_service=(EmptyEstateManagement() if has_estate else None),
                )
            )
        )

        estates_status = client.simulate_get("/estates").status_code
        assert estates_status == estate_status, (
            "estate route presence should follow deps"
        )
        report_status = client.simulate_post(
            "/reports/repositories/acme/widgets"
        ).status_code
        assert (report_status != HTTPStatus.NOT_FOUND) is has_report_route, (
            "reports route presence should follow deps"
        )
