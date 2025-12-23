"""Behavioural tests for GitHub ingestion observability."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import typing as typ

import pytest
from pytest_bdd import given, parsers, scenario, then, when
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ghillie.bronze import GithubIngestionOffset, init_bronze_storage
from ghillie.common.slug import parse_repo_slug
from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker
from ghillie.github.lag import IngestionHealthConfig, IngestionHealthService
from ghillie.github.observability import IngestionEventType
from ghillie.registry import RepositoryRegistryService
from ghillie.silver import init_silver_storage
from ghillie.silver.storage import Repository
from tests.helpers.github_events import (
    create_commit_event,
    create_doc_change_event,
    create_issue_event,
    create_pr_event,
)
from tests.unit.github_ingestion_test_helpers import FakeGitHubClient

if typ.TYPE_CHECKING:
    from pathlib import Path

    from ghillie.github.models import GitHubIngestedEvent


_BASE_TIME = dt.datetime(2099, 1, 1, tzinfo=dt.UTC)


def run_async[T](coro: typ.Coroutine[typ.Any, typ.Any, T]) -> T:
    """Run async coroutines in sync BDD step functions."""
    return asyncio.run(coro)


class ObservabilityContext(typ.TypedDict, total=False):
    """Shared state used by observability BDD steps."""

    session_factory: async_sessionmaker[AsyncSession]
    registry_service: RepositoryRegistryService
    github_client: FakeGitHubClient
    repo_slug: str
    log_records: list[logging.LogRecord]


@scenario(
    "../github_ingestion_observability.feature",
    "Successful ingestion run emits completion metrics",
)
def test_successful_ingestion_emits_completion_metrics() -> None:
    """Behavioural test: successful ingestion logs completion event."""


@scenario(
    "../github_ingestion_observability.feature",
    "Ingestion lag is computable for tracked repositories",
)
def test_ingestion_lag_is_computable() -> None:
    """Behavioural test: lag metrics are available after ingestion."""


@scenario(
    "../github_ingestion_observability.feature",
    "Repository with no ingestion is marked as stalled",
)
def test_repository_with_no_ingestion_is_stalled() -> None:
    """Behavioural test: repos without ingestion are marked stalled."""


@pytest.fixture
def observability_context(tmp_path: Path) -> typ.Iterator[ObservabilityContext]:
    """Provision a fresh database for each scenario."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'observability.db'}")

    async def _init() -> None:
        await init_bronze_storage(engine)
        await init_silver_storage(engine)

    run_async(_init())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    service = RepositoryRegistryService(session_factory, session_factory)
    yield {"session_factory": session_factory, "registry_service": service}
    run_async(engine.dispose())


@given(parsers.parse('a managed repository "{slug}" is registered for ingestion'))
def managed_repository_registered(
    observability_context: ObservabilityContext, slug: str
) -> None:
    """Create a Silver repository row with ingestion enabled."""
    owner, name = parse_repo_slug(slug)
    observability_context["repo_slug"] = slug

    async def _create() -> None:
        async with (
            observability_context["session_factory"]() as session,
            session.begin(),
        ):
            session.add(
                Repository(
                    github_owner=owner,
                    github_name=name,
                    default_branch="main",
                    ingestion_enabled=True,
                    documentation_paths=["docs/roadmap.md"],
                )
            )

    run_async(_create())


def _build_events(
    slug: str,
) -> tuple[
    list[GitHubIngestedEvent],
    list[GitHubIngestedEvent],
    list[GitHubIngestedEvent],
    list[GitHubIngestedEvent],
]:
    """Build test events for the given repository slug."""
    owner, name = parse_repo_slug(slug)
    now = _BASE_TIME

    commits = [create_commit_event(owner, name, now - dt.timedelta(hours=4))]
    prs = [create_pr_event(owner, name, now - dt.timedelta(hours=3))]
    issues = [create_issue_event(owner, name, now - dt.timedelta(hours=2))]
    docs = [create_doc_change_event(owner, name, now - dt.timedelta(hours=1))]

    return commits, prs, issues, docs


@given(parsers.parse('the GitHub API returns activity for "{slug}"'))
def github_api_returns_activity(
    observability_context: ObservabilityContext, slug: str
) -> None:
    """Configure a fake GitHub client that returns activity."""
    commits, prs, issues, docs = _build_events(slug)
    observability_context["github_client"] = FakeGitHubClient(
        commits=commits,
        pull_requests=prs,
        issues=issues,
        doc_changes=docs,
    )


@given(parsers.parse('the GitHub API returns no activity for "{slug}"'))
def github_api_returns_no_activity(
    observability_context: ObservabilityContext, slug: str
) -> None:
    """Configure a fake GitHub client that returns no activity."""
    del slug
    observability_context["github_client"] = FakeGitHubClient(
        commits=[],
        pull_requests=[],
        issues=[],
        doc_changes=[],
    )


@given(parsers.parse('the repository "{slug}" has never been successfully ingested'))
def repository_never_ingested(
    observability_context: ObservabilityContext, slug: str
) -> None:
    """Create an ingestion offset record with no watermarks."""

    async def _create() -> None:
        async with (
            observability_context["session_factory"]() as session,
            session.begin(),
        ):
            session.add(GithubIngestionOffset(repo_external_id=slug))

    run_async(_create())


@when(parsers.parse('the GitHub ingestion worker runs for "{slug}"'))
def run_worker(
    observability_context: ObservabilityContext,
    slug: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Run the ingestion worker once for the specified repository."""

    async def _run() -> None:
        service = observability_context["registry_service"]
        repos = await service.list_active_repositories()
        repo = next(repo for repo in repos if repo.slug == slug)
        worker = GitHubIngestionWorker(
            observability_context["session_factory"],
            observability_context["github_client"],
            config=GitHubIngestionConfig(
                initial_lookback=dt.timedelta(days=1),
                overlap=dt.timedelta(0),
                max_events_per_kind=100,
            ),
        )
        await worker.ingest_repository(repo)

    with caplog.at_level(logging.INFO, logger="ghillie.github.observability"):
        run_async(_run())
    observability_context["log_records"] = list(caplog.records)


@then(parsers.parse('an ingestion run completed log event is emitted for "{slug}"'))
def run_completed_event_emitted(
    observability_context: ObservabilityContext, slug: str
) -> None:
    """Verify that a RUN_COMPLETED log event was emitted."""
    records = observability_context.get("log_records", [])
    completed_records = [
        r for r in records if IngestionEventType.RUN_COMPLETED in r.message
    ]
    assert len(completed_records) == 1
    assert slug in completed_records[0].message


@then("the log event contains the total events ingested")
def log_event_contains_total_events(
    observability_context: ObservabilityContext,
) -> None:
    """Verify that the completion log contains total_events."""
    records = observability_context.get("log_records", [])
    completed_records = [
        r for r in records if IngestionEventType.RUN_COMPLETED in r.message
    ]
    assert len(completed_records) == 1
    assert "total_events=" in completed_records[0].message


@then(parsers.parse('ingestion lag metrics are available for "{slug}"'))
def lag_metrics_available(
    observability_context: ObservabilityContext, slug: str
) -> None:
    """Verify that lag metrics can be queried for the repository."""

    async def _check() -> None:
        service = IngestionHealthService(observability_context["session_factory"])
        metrics = await service.get_lag_for_repository(slug)
        assert metrics is not None
        assert metrics.repo_slug == slug
        assert metrics.time_since_last_ingestion_seconds is not None

    run_async(_check())


@then("the repository is not marked as stalled")
def repository_not_stalled(observability_context: ObservabilityContext) -> None:
    """Verify that the repository is not marked as stalled."""
    slug = observability_context["repo_slug"]

    async def _check() -> None:
        service = IngestionHealthService(observability_context["session_factory"])
        metrics = await service.get_lag_for_repository(slug)
        assert metrics is not None
        assert metrics.is_stalled is False

    run_async(_check())


@then(parsers.parse('the repository "{slug}" is marked as stalled'))
def repository_is_stalled(
    observability_context: ObservabilityContext, slug: str
) -> None:
    """Verify that the repository is marked as stalled."""

    async def _check() -> None:
        # Use a very short threshold to ensure stalled detection
        config = IngestionHealthConfig(stalled_threshold=dt.timedelta(seconds=1))
        service = IngestionHealthService(
            observability_context["session_factory"], config=config
        )
        metrics = await service.get_lag_for_repository(slug)
        assert metrics is not None
        assert metrics.is_stalled is True

    run_async(_check())
