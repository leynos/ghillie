"""Behavioural tests for catalogue-driven GitHub noise filters."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import msgspec
import pytest
from pytest_bdd import given, parsers, scenario, then, when
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ghillie.bronze import RawEvent, init_bronze_storage
from ghillie.catalogue.models import NoiseFilters, NoiseFilterToggles
from ghillie.catalogue.storage import (
    ComponentRecord,
    Estate,
    ProjectRecord,
    RepositoryRecord,
    init_catalogue_storage,
)
from ghillie.common.slug import parse_repo_slug
from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker
from ghillie.github.models import GitHubIngestedEvent
from ghillie.registry import RepositoryRegistryService
from ghillie.silver import init_silver_storage
from ghillie.silver.storage import Repository
from tests.unit.github_ingestion_test_helpers import FakeGitHubClient

if typ.TYPE_CHECKING:
    from pathlib import Path


_BASE_TIME = dt.datetime(2099, 1, 1, tzinfo=dt.UTC)


def run_async[T](coro: typ.Coroutine[typ.Any, typ.Any, T]) -> T:
    """Run async coroutines in sync BDD step functions."""
    return asyncio.run(coro)


class NoiseIngestionContext(typ.TypedDict, total=False):
    """Shared state used by BDD steps."""

    session_factory: async_sessionmaker[AsyncSession]
    registry_service: RepositoryRegistryService
    github_client: FakeGitHubClient
    project_id: str
    repo_slug: str
    human_commit_id: str
    bot_commit_id: str
    new_bot_commit_id: str


@typ.final
class _CommitSpec(typ.TypedDict):
    sha: str
    occurred_at: dt.datetime
    author_name: str
    cursor: str


def _commit_event(slug: str, spec: _CommitSpec) -> GitHubIngestedEvent:
    owner, name = parse_repo_slug(slug)
    sha = spec["sha"]
    occurred_at = spec["occurred_at"]
    author_name = spec["author_name"]
    cursor = spec["cursor"]
    return GitHubIngestedEvent(
        event_type="github.commit",
        source_event_id=sha,
        occurred_at=occurred_at,
        payload={
            "sha": sha,
            "repo_owner": owner,
            "repo_name": name,
            "default_branch": "main",
            "committed_at": occurred_at.isoformat(),
            "author_name": author_name,
            "message": "chore: bump deps" if "bot" in author_name else "feat: add api",
        },
        cursor=cursor,
    )


@scenario(
    "../github_noise_filters.feature",
    "Toggling a noise filter changes subsequent ingestion",
)
def test_noise_filter_toggle_changes_ingestion() -> None:
    """Behavioural test: catalogue noise filter toggles affect ingestion."""


@pytest.fixture
def ingestion_context(tmp_path: Path) -> typ.Iterator[NoiseIngestionContext]:
    """Provision a fresh database for each scenario."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'noise_ingestion.db'}"
    )

    async def _init() -> None:
        await init_bronze_storage(engine)
        await init_silver_storage(engine)
        await init_catalogue_storage(engine)

    run_async(_init())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = RepositoryRegistryService(session_factory, session_factory)
    yield {"session_factory": session_factory, "registry_service": service}
    run_async(engine.dispose())


@given(
    parsers.parse(
        'a managed repository "{slug}" exists in the catalogue with bot author '
        "filtering enabled"
    )
)
def managed_repository_with_noise_filter(
    ingestion_context: NoiseIngestionContext, slug: str
) -> None:
    """Create catalogue + Silver rows for a managed repository with noise config."""
    owner, name = parse_repo_slug(slug)
    ingestion_context["repo_slug"] = slug

    noise = NoiseFilters(
        toggles=NoiseFilterToggles(ignore_authors=True),
        ignore_authors=["dependabot[bot]"],
    )

    async def _create() -> None:
        async with ingestion_context["session_factory"]() as session, session.begin():
            estate = Estate(key="noise", name="Noise Estate")
            session.add(estate)
            await session.flush()

            repo_record = RepositoryRecord(
                owner=owner,
                name=name,
                default_branch="main",
                documentation_paths=["docs/roadmap.md"],
            )
            session.add(repo_record)
            await session.flush()

            project = ProjectRecord(
                estate_id=estate.id,
                key="reef",
                name="Reef",
                noise=msgspec.to_builtins(noise),
                status_preferences={},
                documentation_paths=[],
            )
            session.add(project)
            await session.flush()
            ingestion_context["project_id"] = project.id

            session.add(
                ComponentRecord(
                    project_id=project.id,
                    repository_id=repo_record.id,
                    key="reef-api",
                    name="Reef API",
                    type="service",
                    lifecycle="active",
                    notes=[],
                )
            )

            session.add(
                Repository(
                    github_owner=owner,
                    github_name=name,
                    default_branch="main",
                    ingestion_enabled=True,
                    documentation_paths=["docs/roadmap.md"],
                    estate_id=estate.id,
                    catalogue_repository_id=repo_record.id,
                )
            )

    run_async(_create())


@given(
    parsers.parse('the GitHub API returns a bot commit and a human commit for "{slug}"')
)
def github_api_returns_bot_and_human_commits(
    ingestion_context: NoiseIngestionContext, slug: str
) -> None:
    """Configure a fake GitHub client that includes both bot and human commits."""
    bot_sha = "bot-1"
    human_sha = "human-1"
    ingestion_context["bot_commit_id"] = bot_sha
    ingestion_context["human_commit_id"] = human_sha

    bot = _commit_event(
        slug,
        {
            "sha": bot_sha,
            "occurred_at": _BASE_TIME - dt.timedelta(hours=2),
            "author_name": "dependabot[bot]",
            "cursor": "cursor-bot-1",
        },
    )
    human = _commit_event(
        slug,
        {
            "sha": human_sha,
            "occurred_at": _BASE_TIME - dt.timedelta(hours=1),
            "author_name": "alice",
            "cursor": "cursor-human-1",
        },
    )
    ingestion_context["github_client"] = FakeGitHubClient(
        commits=[human, bot],
        pull_requests=[],
        issues=[],
        doc_changes=[],
    )


def _run_worker(ingestion_context: NoiseIngestionContext, slug: str) -> None:
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


@when(parsers.parse('the GitHub ingestion worker runs for "{slug}"'))
def run_worker(ingestion_context: NoiseIngestionContext, slug: str) -> None:
    """Run the ingestion worker once."""
    _run_worker(ingestion_context, slug)


@then(parsers.parse('only the human commit is ingested for "{slug}"'))
def only_human_commit_ingested(
    ingestion_context: NoiseIngestionContext, slug: str
) -> None:
    """Assert the bot commit is filtered while the human commit is persisted."""
    human_sha = ingestion_context["human_commit_id"]
    bot_sha = ingestion_context["bot_commit_id"]

    async def _assert() -> None:
        async with ingestion_context["session_factory"]() as session:
            events = (
                await session.scalars(
                    select(RawEvent).where(
                        RawEvent.repo_external_id == slug,
                        RawEvent.event_type == "github.commit",
                    )
                )
            ).all()
            source_ids = {event.source_event_id for event in events}
            assert human_sha in source_ids
            assert bot_sha not in source_ids

    run_async(_assert())


@when("the catalogue disables bot author filtering for the repository project")
def disable_bot_author_filter(ingestion_context: NoiseIngestionContext) -> None:
    """Update the project noise toggles to disable author filtering."""
    project_id = ingestion_context["project_id"]

    async def _update() -> None:
        async with ingestion_context["session_factory"]() as session, session.begin():
            project = await session.get(ProjectRecord, project_id)
            assert project is not None
            noise = dict(project.noise)
            toggles = dict(noise.get("toggles", {}))
            toggles["ignore_authors"] = False
            noise["toggles"] = toggles
            project.noise = noise

    run_async(_update())


@when(parsers.parse('the GitHub API returns a new bot commit for "{slug}"'))
def github_api_returns_new_bot_commit(
    ingestion_context: NoiseIngestionContext, slug: str
) -> None:
    """Configure the GitHub API to return a newer bot commit after the toggle."""
    sha = "bot-2"
    ingestion_context["new_bot_commit_id"] = sha
    new_bot = _commit_event(
        slug,
        {
            "sha": sha,
            "occurred_at": _BASE_TIME + dt.timedelta(hours=1),
            "author_name": "dependabot[bot]",
            "cursor": "cursor-bot-2",
        },
    )
    ingestion_context["github_client"] = FakeGitHubClient(
        commits=[new_bot],
        pull_requests=[],
        issues=[],
        doc_changes=[],
    )


@when(parsers.parse('the GitHub ingestion worker runs again for "{slug}"'))
def run_worker_again(ingestion_context: NoiseIngestionContext, slug: str) -> None:
    """Run the ingestion worker again."""
    _run_worker(ingestion_context, slug)


@then(parsers.parse('the new bot commit is ingested for "{slug}"'))
def new_bot_commit_ingested(
    ingestion_context: NoiseIngestionContext, slug: str
) -> None:
    """Assert the newer bot commit is persisted after disabling the filter."""
    sha = ingestion_context["new_bot_commit_id"]

    async def _assert() -> None:
        async with ingestion_context["session_factory"]() as session:
            events = (
                await session.scalars(
                    select(RawEvent).where(
                        RawEvent.repo_external_id == slug,
                        RawEvent.event_type == "github.commit",
                    )
                )
            ).all()
            source_ids = {event.source_event_id for event in events}
            assert sha in source_ids

    run_async(_assert())
