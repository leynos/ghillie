"""Behavioural tests for incremental GitHub ingestion."""

from __future__ import annotations

import asyncio
import dataclasses
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

from ghillie.bronze import RawEvent, init_bronze_storage
from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker
from ghillie.github.models import GitHubIngestedEvent
from ghillie.registry import RepositoryRegistryService
from ghillie.silver import init_silver_storage
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    from pathlib import Path


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


class FakeGitHubClient:
    """Deterministic GitHub client for behavioural tests."""

    def __init__(self, events: list[GitHubIngestedEvent]) -> None:
        """Store a fixed event list returned by iterator methods."""
        self._events = events

    async def iter_commits(
        self, repo: object, *, since: dt.datetime
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield commit events newer than `since`."""
        for event in self._events:
            if event.event_type == "github.commit" and event.occurred_at > since:
                yield event

    async def iter_pull_requests(
        self, repo: object, *, since: dt.datetime
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield pull request events newer than `since`."""
        for event in self._events:
            if event.event_type == "github.pull_request" and event.occurred_at > since:
                yield event

    async def iter_issues(
        self, repo: object, *, since: dt.datetime
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield issue events newer than `since`."""
        for event in self._events:
            if event.event_type == "github.issue" and event.occurred_at > since:
                yield event

    async def iter_doc_changes(
        self,
        repo: object,
        *,
        since: dt.datetime,
        documentation_paths: typ.Sequence[str],
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield documentation change events newer than `since`."""
        del documentation_paths
        for event in self._events:
            if event.event_type == "github.doc_change" and event.occurred_at > since:
                yield event


class IngestionContext(typ.TypedDict, total=False):
    """Shared state used by BDD steps."""

    session_factory: async_sessionmaker[AsyncSession]
    registry_service: RepositoryRegistryService
    github_client: FakeGitHubClient
    repo_slug: str
    raw_event_count_before: int


def _create_commit_event(
    owner: str, name: str, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    return GitHubIngestedEvent(
        event_type="github.commit",
        source_event_id="abc123",
        occurred_at=occurred_at,
        payload={
            "sha": "abc123",
            "message": "docs: refresh roadmap",
            "repo_owner": owner,
            "repo_name": name,
            "default_branch": "main",
            "committed_at": occurred_at.isoformat(),
            "metadata": {"branch": "main"},
        },
    )


@dataclasses.dataclass(frozen=True, slots=True)
class _NumberedItemSpec:
    """Specification for creating a test numbered item event (PR or issue)."""

    event_type: str
    item_id: int
    title: str
    extra_fields: dict[str, object] | None = None


def _create_numbered_item_event(
    owner: str,
    name: str,
    occurred_at: dt.datetime,
    spec: _NumberedItemSpec,
) -> GitHubIngestedEvent:
    """Create a test event for numbered GitHub items (PRs or issues)."""
    payload: dict[str, object] = {
        "id": spec.item_id,
        "number": spec.item_id,
        "title": spec.title,
        "state": "open",
        "repo_owner": owner,
        "repo_name": name,
        "created_at": occurred_at.isoformat(),
        "metadata": {"updated_at": occurred_at.isoformat()},
    }
    if spec.extra_fields is not None:
        payload |= spec.extra_fields

    return GitHubIngestedEvent(
        event_type=spec.event_type,
        source_event_id=str(spec.item_id),
        occurred_at=occurred_at,
        payload=payload,
    )


def _create_pr_event(
    owner: str, name: str, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    spec = _NumberedItemSpec(
        event_type="github.pull_request",
        item_id=17,
        title="Add release checklist",
        extra_fields={
            "base_branch": "main",
            "head_branch": "feature/release-checklist",
        },
    )
    return _create_numbered_item_event(owner, name, occurred_at, spec)


def _create_issue_event(
    owner: str, name: str, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    spec = _NumberedItemSpec(
        event_type="github.issue",
        item_id=101,
        title="Fix flaky integration test",
        extra_fields=None,
    )
    return _create_numbered_item_event(owner, name, occurred_at, spec)


def _create_doc_change_event(
    owner: str, name: str, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    return GitHubIngestedEvent(
        event_type="github.doc_change",
        source_event_id="abc123:docs/roadmap.md",
        occurred_at=occurred_at,
        payload={
            "commit_sha": "abc123",
            "path": "docs/roadmap.md",
            "change_type": "modified",
            "repo_owner": owner,
            "repo_name": name,
            "occurred_at": occurred_at.isoformat(),
            "is_roadmap": True,
            "is_adr": False,
            "metadata": {"message": "docs: refresh roadmap"},
        },
    )


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
    now = dt.datetime.now(dt.UTC)
    events = [
        _create_commit_event(owner, name, now - dt.timedelta(hours=4)),
        _create_pr_event(owner, name, now - dt.timedelta(hours=3)),
        _create_issue_event(owner, name, now - dt.timedelta(hours=2)),
        _create_doc_change_event(owner, name, now - dt.timedelta(hours=1)),
    ]
    ingestion_context["github_client"] = FakeGitHubClient(events)


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

    async def _assert() -> None:
        async with ingestion_context["session_factory"]() as session:
            events = (
                await session.scalars(
                    select(RawEvent).where(RawEvent.repo_external_id == slug)
                )
            ).all()
            assert {event.event_type for event in events} == {
                "github.commit",
                "github.pull_request",
                "github.issue",
                "github.doc_change",
            }

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
