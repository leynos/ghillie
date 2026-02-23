"""Behavioural coverage for on-demand report generation via HTTP API.

Usage
-----
Run with pytest::

    pytest tests/features/steps/test_on_demand_report_steps.py

These tests require the ``session_factory`` fixture from ``conftest.py``
and a running py-pglite database.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ
from http import HTTPStatus

import falcon.testing
import pytest
from pytest_bdd import given, parsers, scenario, then, when

from ghillie.api.app import AppDependencies, create_app
from ghillie.bronze import RawEventWriter
from ghillie.evidence import EvidenceBundleService
from ghillie.reporting import (
    ReportingConfig,
    ReportingService,
    ReportingServiceDependencies,
)
from ghillie.silver import RawEventTransformer, Repository
from ghillie.status import MockStatusModel
from tests.helpers.event_builders import commit_envelope

if typ.TYPE_CHECKING:
    from falcon.testing.client import Result
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _build_reporting_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> ReportingService:
    """Build a configured ReportingService for tests."""
    deps = ReportingServiceDependencies(
        session_factory=session_factory,
        evidence_service=EvidenceBundleService(session_factory),
        status_model=MockStatusModel(),
    )
    return ReportingService(deps, config=ReportingConfig(window_days=7))


def _build_api_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> falcon.testing.TestClient:
    """Build a Falcon test client with full domain dependencies."""
    reporting_service = _build_reporting_service(session_factory)
    deps = AppDependencies(
        session_factory=session_factory,
        reporting_service=reporting_service,
    )
    return falcon.testing.TestClient(create_app(deps))


@pytest.fixture
def api_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> falcon.testing.TestClient:
    """Provide a Falcon test client wired to the real database."""
    return _build_api_client(session_factory)


class OnDemandContext(typ.TypedDict, total=False):
    """Mutable context shared between steps."""

    session_factory: async_sessionmaker[AsyncSession]
    client: falcon.testing.TestClient
    owner: str
    name: str
    response: Result


@scenario("../on_demand_report.feature", "Generate report for a repository with events")
def test_generate_report_on_demand() -> None:
    """Wrapper for pytest-bdd scenario."""


@scenario("../on_demand_report.feature", "Return 204 when no events in window")
def test_no_events_returns_204() -> None:
    """Wrapper for pytest-bdd scenario."""


@scenario("../on_demand_report.feature", "Return 404 for unknown repository")
def test_unknown_repo_returns_404() -> None:
    """Wrapper for pytest-bdd scenario."""


@given(
    "a running API with a repository that has events",
    target_fixture="on_demand_context",
)
def given_api_with_events(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: falcon.testing.TestClient,
) -> OnDemandContext:
    """Set up an API with a repository containing events."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    async def _setup() -> tuple[str, str]:
        owner, name = "acme", "widgets"
        # Use a recent timestamp so the event falls within the default
        # 7-day reporting window when run_for_repository uses utcnow().
        commit_time = dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
        await writer.ingest(
            commit_envelope(
                f"{owner}/{name}", "abc123", commit_time, "feat: new feature"
            )
        )
        await transformer.process_pending()
        return owner, name

    owner, name = asyncio.run(_setup())
    return {
        "session_factory": session_factory,
        "client": api_client,
        "owner": owner,
        "name": name,
    }


@given(
    "a running API with a repository but no events",
    target_fixture="on_demand_context",
)
def given_api_without_events(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: falcon.testing.TestClient,
) -> OnDemandContext:
    """Set up an API with a repository but no events."""

    async def _setup() -> tuple[str, str]:
        async with session_factory() as session, session.begin():
            repo = Repository(
                github_owner="empty",
                github_name="repo",
                default_branch="main",
                ingestion_enabled=True,
            )
            session.add(repo)
        return "empty", "repo"

    owner, name = asyncio.run(_setup())
    return {
        "session_factory": session_factory,
        "client": api_client,
        "owner": owner,
        "name": name,
    }


@given(
    "a running API with no repositories",
    target_fixture="on_demand_context",
)
def given_api_no_repos(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: falcon.testing.TestClient,
) -> OnDemandContext:
    """Set up an API with no repositories at all."""
    return {
        "session_factory": session_factory,
        "client": api_client,
        "owner": "unknown",
        "name": "repo",
    }


@when("I POST to /reports/repositories/{owner}/{name}")
def when_post_report(on_demand_context: OnDemandContext) -> None:
    """Issue a POST request to generate a report."""
    owner = on_demand_context["owner"]
    name = on_demand_context["name"]
    client = on_demand_context["client"]
    on_demand_context["response"] = client.simulate_post(
        f"/reports/repositories/{owner}/{name}"
    )


@when("I POST to /reports/repositories/unknown/repo")
def when_post_unknown_repo(on_demand_context: OnDemandContext) -> None:
    """Issue a POST for a non-existent repository."""
    client = on_demand_context["client"]
    on_demand_context["response"] = client.simulate_post(
        "/reports/repositories/unknown/repo"
    )


@then(parsers.parse("the response status is {status:d}"))
def then_response_status(on_demand_context: OnDemandContext, status: int) -> None:
    """Assert the HTTP response status code and basic response contract."""
    response = on_demand_context["response"]
    assert response.status_code == status, (
        f"expected status {status}, got {response.status_code}"
    )

    if status == HTTPStatus.NO_CONTENT:
        # 204 No Content responses must not have a body
        assert response.content in (
            b"",
            None,
        ), "204 response must not have a body"

    elif status == HTTPStatus.NOT_FOUND:
        # 404 responses should include a JSON error payload
        body = response.json
        assert body is not None, "404 response must contain a JSON error body"
        assert "title" in body, "404 response missing title"
        assert "description" in body, "404 response missing description"


@then("the response body contains report metadata")
def then_response_has_metadata(on_demand_context: OnDemandContext) -> None:
    """Assert the response body includes expected report fields."""
    response = on_demand_context["response"]
    body = response.json
    assert "report_id" in body, "Missing report_id"
    assert "repository" in body, "Missing repository"
    assert "window_start" in body, "Missing window_start"
    assert "window_end" in body, "Missing window_end"
    assert "generated_at" in body, "Missing generated_at"
    assert "status" in body, "Missing status"
    assert "model" in body, "Missing model"


@then("the response body contains an error description")
def then_response_has_error(on_demand_context: OnDemandContext) -> None:
    """Assert the response body includes an error description."""
    response = on_demand_context["response"]
    body = response.json
    assert "title" in body, "Missing title"
    assert "description" in body, "Missing description"
