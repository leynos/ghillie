"""Behavioural tests for incremental GitHub ingestion."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import pytest
from pytest_bdd import given, parsers, scenario, then, when
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ghillie.bronze import GithubIngestionOffset, RawEvent, init_bronze_storage
from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker
from ghillie.registry import RepositoryRegistryService
from ghillie.silver import init_silver_storage
from ghillie.silver.storage import Repository
from tests.helpers.github_events import (
    _create_commit_event,
    _create_doc_change_event,
    _create_issue_event,
    _create_pr_event,
)
from tests.unit.github_ingestion_test_helpers import (
    FakeGitHubClient,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

    from ghillie.github.models import GitHubIngestedEvent


_BASE_TIME = dt.datetime(2099, 1, 1, tzinfo=dt.UTC)


def run_async[T](coro: typ.Coroutine[typ.Any, typ.Any, T]) -> T:
    """Run async coroutines in sync BDD step functions."""
    return asyncio.run(coro)


def _count_raw_events(ingestion_context: IngestionContext, slug: str) -> int:
    """Count raw events for a given repository slug."""

    async def _count() -> int:
        async with ingestion_context["session_factory"]() as session:
            ids = (
                await session.scalars(
                    select(RawEvent.id).where(RawEvent.repo_external_id == slug)
                )
            ).all()
            return len(ids)

    return run_async(_count())


class IngestionContext(typ.TypedDict, total=False):
    """Shared state used by BDD steps."""

    session_factory: async_sessionmaker[AsyncSession]
    registry_service: RepositoryRegistryService
    github_client: FakeGitHubClient
    repo_slug: str
    raw_event_count_before: int
    expected_offsets: dict[str, dt.datetime]


def _configure_fake_github_client(  # noqa: PLR0913
    ingestion_context: IngestionContext,
    slug: str,
    *,
    commits: list[GitHubIngestedEvent],
    pull_requests: list[GitHubIngestedEvent],
    issues: list[GitHubIngestedEvent],
    doc_changes: list[GitHubIngestedEvent],
    expected_offsets: dict[str, dt.datetime],
) -> None:
    """Configure a FakeGitHubClient and expected offsets for the ingestion context."""
    del slug
    ingestion_context["github_client"] = FakeGitHubClient(
        commits=commits,
        pull_requests=pull_requests,
        issues=issues,
        doc_changes=doc_changes,
    )
    ingestion_context["expected_offsets"] = expected_offsets


@scenario(
    "../github_incremental_ingestion.feature",
    "New GitHub activity is captured into raw events",
)
def test_incremental_ingestion() -> None:
    """Behavioural test: worker appends new activity to raw_events."""


@pytest.fixture
def ingestion_context(tmp_path: Path) -> typ.Iterator[IngestionContext]:
    """Provision a fresh database for each scenario."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ingestion.db'}")

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
    ingestion_context: IngestionContext, slug: str
) -> None:
    """Create a Silver repository row with ingestion enabled."""
    owner, name = slug.split("/", 1)
    ingestion_context["repo_slug"] = slug

    async def _create() -> None:
        async with ingestion_context["session_factory"]() as session, session.begin():
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


@given(parsers.parse('the GitHub API returns activity for "{slug}"'))
def github_api_returns_activity(ingestion_context: IngestionContext, slug: str) -> None:
    """Configure a fake GitHub client that returns a fixed activity set."""
    owner, name = slug.split("/", 1)
    now = _BASE_TIME
    _configure_fake_github_client(
        ingestion_context,
        slug,
        commits=[_create_commit_event(owner, name, now - dt.timedelta(hours=4))],
        pull_requests=[_create_pr_event(owner, name, now - dt.timedelta(hours=3))],
        issues=[_create_issue_event(owner, name, now - dt.timedelta(hours=2))],
        doc_changes=[
            _create_doc_change_event(owner, name, now - dt.timedelta(hours=1))
        ],
        expected_offsets={
            "commit": now - dt.timedelta(hours=4),
            "pull_request": now - dt.timedelta(hours=3),
            "issue": now - dt.timedelta(hours=2),
            "doc": now - dt.timedelta(hours=1),
        },
    )


@given(parsers.parse('the GitHub API returns additional activity for "{slug}"'))
def github_api_returns_additional_activity(
    ingestion_context: IngestionContext, slug: str
) -> None:
    """Add additional activity with timestamps after the initial ingestion run."""
    owner, name = slug.split("/", 1)
    now = _BASE_TIME
    _configure_fake_github_client(
        ingestion_context,
        slug,
        commits=[
            _create_commit_event(owner, name, now - dt.timedelta(hours=4)),
            _create_commit_event(owner, name, now + dt.timedelta(hours=1)),
        ],
        pull_requests=[
            _create_pr_event(owner, name, now - dt.timedelta(hours=3)),
            _create_pr_event(owner, name, now + dt.timedelta(hours=2)),
        ],
        issues=[_create_issue_event(owner, name, now - dt.timedelta(hours=2))],
        doc_changes=[
            _create_doc_change_event(owner, name, now - dt.timedelta(hours=1))
        ],
        expected_offsets={
            "commit": now + dt.timedelta(hours=1),
            "pull_request": now + dt.timedelta(hours=2),
            "issue": now - dt.timedelta(hours=2),
            "doc": now - dt.timedelta(hours=1),
        },
    )


@when(parsers.parse('the GitHub ingestion worker runs for "{slug}"'))
def run_worker(ingestion_context: IngestionContext, slug: str) -> None:
    """Run the ingestion worker once for the specified repository."""

    async def _run() -> None:
        service = ingestion_context["registry_service"]
        repos = await service.list_active_repositories()
        repo = next(repo for repo in repos if repo.slug == slug)
        worker = GitHubIngestionWorker(
            ingestion_context["session_factory"],
            ingestion_context["github_client"],
            config=GitHubIngestionConfig(
                initial_lookback=dt.timedelta(days=1),
                overlap=dt.timedelta(0),
                max_events_per_kind=100,
            ),
        )
        await worker.ingest_repository(repo)

    run_async(_run())


@then(parsers.parse('Bronze raw events exist for "{slug}"'))
def raw_events_exist(ingestion_context: IngestionContext, slug: str) -> None:
    """Verify expected event types exist in the Bronze store."""
    owner, name = slug.split("/", 1)

    async def _assert() -> None:
        async with ingestion_context["session_factory"]() as session:
            events = (
                await session.scalars(
                    select(RawEvent).where(RawEvent.repo_external_id == slug)
                )
            ).all()
            event_types = {event.event_type for event in events}
            assert event_types == {
                "github.commit",
                "github.pull_request",
                "github.issue",
                "github.doc_change",
            }

            by_type = {event.event_type: event for event in events}
            commit_payload = by_type["github.commit"].payload
            assert commit_payload["repo_owner"] == owner
            assert commit_payload["repo_name"] == name
            assert isinstance(commit_payload.get("sha"), str)

            pr_payload = by_type["github.pull_request"].payload
            assert pr_payload["repo_owner"] == owner
            assert pr_payload["repo_name"] == name
            assert isinstance(pr_payload.get("number"), int)
            assert isinstance(pr_payload.get("title"), str)

            issue_payload = by_type["github.issue"].payload
            assert issue_payload["repo_owner"] == owner
            assert issue_payload["repo_name"] == name
            assert isinstance(issue_payload.get("title"), str)

            doc_payload = by_type["github.doc_change"].payload
            assert doc_payload["repo_owner"] == owner
            assert doc_payload["repo_name"] == name
            assert doc_payload["path"] == "docs/roadmap.md"
            assert doc_payload["is_roadmap"] is True
            assert doc_payload["is_adr"] is False

    run_async(_assert())


@when(parsers.parse('the GitHub ingestion worker runs again for "{slug}"'))
def run_worker_again(ingestion_context: IngestionContext, slug: str) -> None:
    """Record raw event count, then re-run ingestion."""
    ingestion_context["raw_event_count_before"] = _count_raw_events(
        ingestion_context, slug
    )
    run_worker(ingestion_context, slug)


@then(parsers.parse('no additional Bronze raw events are written for "{slug}"'))
def no_additional_events(ingestion_context: IngestionContext, slug: str) -> None:
    """Assert the second ingestion run does not add duplicates."""
    after = _count_raw_events(ingestion_context, slug)
    assert after == ingestion_context["raw_event_count_before"]


@then(parsers.parse('additional Bronze raw events are written for "{slug}"'))
def additional_events_are_written(
    ingestion_context: IngestionContext, slug: str
) -> None:
    """Assert the second ingestion run adds new activity."""
    after = _count_raw_events(ingestion_context, slug)
    assert after > ingestion_context["raw_event_count_before"]


@then(parsers.parse('GitHub ingestion offsets advance for "{slug}"'))
def offsets_advance(ingestion_context: IngestionContext, slug: str) -> None:
    """Verify per-kind ingestion offsets match expected timestamps."""
    expected = ingestion_context["expected_offsets"]

    async def _assert() -> None:
        async with ingestion_context["session_factory"]() as session:
            offsets = await session.scalar(
                select(GithubIngestionOffset).where(
                    GithubIngestionOffset.repo_external_id == slug
                )
            )
            assert offsets is not None
            assert offsets.last_commit_ingested_at == expected["commit"]
            assert offsets.last_pr_ingested_at == expected["pull_request"]
            assert offsets.last_issue_ingested_at == expected["issue"]
            assert offsets.last_doc_ingested_at == expected["doc"]

    run_async(_assert())
