"""Unit tests for GitHub ingestion noise filtering."""

from __future__ import annotations

import datetime as dt
import typing as typ
from dataclasses import dataclass  # noqa: ICN003

import msgspec
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from ghillie.bronze import GithubIngestionOffset, RawEvent
from ghillie.catalogue.models import NoiseFilters
from ghillie.catalogue.storage import (
    ComponentRecord,
    Estate,
    ProjectRecord,
    RepositoryRecord,
)
from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker
from ghillie.github.noise import CompiledNoiseFilters
from tests.unit.github_ingestion_test_helpers import (
    EventSpec,
    FakeGitHubClient,
    make_event,
    make_repo_info,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.github.models import GitHubIngestedEvent
    from ghillie.registry.models import RepositoryInfo


async def _setup_catalogue_with_noise(
    session_factory: async_sessionmaker[AsyncSession],
    repo: RepositoryInfo,
    noise: NoiseFilters,
) -> None:
    """Set up estate, repository, project, and component with noise configuration."""
    async with session_factory() as session, session.begin():
        estate = Estate(key="noise-estate", name="Noise Estate")
        session.add(estate)
        await session.flush()

        repo_record = RepositoryRecord(
            owner=repo.owner,
            name=repo.name,
            default_branch=repo.default_branch,
            documentation_paths=[],
        )
        session.add(repo_record)
        await session.flush()

        project = ProjectRecord(
            estate_id=estate.id,
            key="noise-project",
            name="Noise Project",
            noise=msgspec.to_builtins(noise),
            status_preferences={},
            documentation_paths=[],
        )
        session.add(project)
        await session.flush()

        session.add(
            ComponentRecord(
                project_id=project.id,
                repository_id=repo_record.id,
                key="noise-component",
                name="Noise Component",
                type="service",
                lifecycle="active",
                notes=[],
            )
        )


def _make_bot_commit_event(
    repo: RepositoryInfo,
    occurred_at: dt.datetime,
) -> tuple[GitHubIngestedEvent, str]:
    """Create a bot commit event for noise filtering tests."""
    sha = "bot-commit"
    event = make_event(
        occurred_at,
        EventSpec(
            event_type="github.commit",
            source_event_id=sha,
            payload={
                "sha": sha,
                "repo_owner": repo.owner,
                "repo_name": repo.name,
                "default_branch": repo.default_branch,
                "committed_at": occurred_at.isoformat(),
                "author_name": "dependabot[bot]",
                "message": "chore: bump deps",
            },
            cursor="cursor-1",
        ),
    )
    return (event, sha)


@dataclass(frozen=True)
class MultiProjectCatalogueSetup:
    """Configuration for setting up a multi-project catalogue in tests."""

    estate_key: str
    estate_name: str
    repo: RepositoryInfo
    projects: list[tuple[str, str, NoiseFilters]]


async def _setup_multi_project_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
    config: MultiProjectCatalogueSetup,
) -> None:
    """Set up catalogue with multiple projects referencing the same repository.

    Args:
        session_factory: Database session factory
        config: Multi-project catalogue configuration

    """
    async with session_factory() as session, session.begin():
        estate = Estate(key=config.estate_key, name=config.estate_name)
        session.add(estate)
        await session.flush()

        repo_record = RepositoryRecord(
            owner=config.repo.owner,
            name=config.repo.name,
            default_branch=config.repo.default_branch,
            documentation_paths=[],
        )
        session.add(repo_record)
        await session.flush()

        for project_key, project_name, noise in config.projects:
            project = ProjectRecord(
                estate_id=estate.id,
                key=project_key,
                name=project_name,
                noise=msgspec.to_builtins(noise),
                status_preferences={},
                documentation_paths=[],
            )
            session.add(project)
            await session.flush()

            session.add(
                ComponentRecord(
                    project_id=project.id,
                    repository_id=repo_record.id,
                    key=f"{project_key}-component",
                    name=f"{project_name} Component",
                    type="service",
                    lifecycle="active",
                    notes=[],
                )
            )


@pytest.mark.asyncio
async def test_ingestion_applies_project_noise_filters_from_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Catalogue-defined noise filters drop bot events before Bronze persistence."""
    # Arrange
    repo = make_repo_info()
    now = dt.datetime.now(dt.UTC)
    occurred_at = now - dt.timedelta(minutes=10)
    noise = NoiseFilters(ignore_authors=["dependabot[bot]"])
    await _setup_catalogue_with_noise(session_factory, repo, noise)
    event, _sha = _make_bot_commit_event(repo, occurred_at)
    client = FakeGitHubClient(
        commits=[event],
        pull_requests=[],
        issues=[],
        doc_changes=[],
    )
    worker = GitHubIngestionWorker(
        session_factory,
        client,
        config=GitHubIngestionConfig(
            overlap=dt.timedelta(0),
            initial_lookback=dt.timedelta(days=1),
        ),
    )

    # Act
    result = await worker.ingest_repository(repo)
    assert result.commits_ingested == 0

    # Assert
    async with session_factory() as session:
        raw_events = (
            await session.scalars(
                select(RawEvent).where(RawEvent.repo_external_id == repo.slug)
            )
        ).all()
        assert raw_events == []
        offsets = await session.scalar(
            select(GithubIngestionOffset).where(
                GithubIngestionOffset.repo_external_id == repo.slug
            )
        )
        assert offsets is not None
        assert offsets.last_commit_ingested_at == occurred_at


@pytest.mark.parametrize(
    (
        "estate_key",
        "noise_a",
        "noise_b",
        "project_a_key",
        "project_b_key",
        "expected_authors",
        "expected_labels",
        "expected_paths",
        "expected_prefixes",
    ),
    [
        pytest.param(
            "noise-estate-merge",
            NoiseFilters(ignore_authors=["dependabot[bot]"]),
            NoiseFilters(
                ignore_labels=["chore/deps"],
                ignore_paths=["docs/", "docs"],
                ignore_title_prefixes=["Chore:"],
            ),
            "noise-project-a",
            "noise-project-b",
            frozenset({"dependabot[bot]"}),
            frozenset({"chore/deps"}),
            ("docs",),
            ("chore:",),
            id="merges_multiple_projects",
        ),
        pytest.param(
            "noise-estate-disabled",
            NoiseFilters(ignore_authors=["dependabot[bot]"]),
            NoiseFilters(
                enabled=False,
                ignore_labels=["chore/deps"],
                ignore_paths=["docs/**"],
                ignore_title_prefixes=["chore:"],
            ),
            "noise-project-enabled",
            "noise-project-disabled",
            frozenset({"dependabot[bot]"}),
            frozenset(),
            (),
            (),
            id="skips_disabled_projects",
        ),
    ],
)
@pytest.mark.asyncio
async def test_compile_noise_filters(  # noqa: PLR0913
    session_factory: async_sessionmaker[AsyncSession],
    estate_key: str,
    noise_a: NoiseFilters,
    noise_b: NoiseFilters,
    project_a_key: str,
    project_b_key: str,
    expected_authors: frozenset[str],
    expected_labels: frozenset[str],
    expected_paths: tuple[str, ...],
    expected_prefixes: tuple[str, ...],
) -> None:
    """_compile_noise_filters merges enabled projects and skips disabled ones."""
    repo = make_repo_info()
    await _setup_multi_project_catalogue(
        session_factory,
        MultiProjectCatalogueSetup(
            estate_key=estate_key,
            estate_name="Noise Estate",
            repo=repo,
            projects=[
                (
                    project_a_key,
                    f"Noise Project {project_a_key}",
                    noise_a,
                ),
                (
                    project_b_key,
                    f"Noise Project {project_b_key}",
                    noise_b,
                ),
            ],
        ),
    )

    worker = GitHubIngestionWorker(
        session_factory,
        FakeGitHubClient(commits=[], pull_requests=[], issues=[], doc_changes=[]),
    )
    compiled = await worker._compile_noise_filters(repo)
    assert compiled.ignore_authors == expected_authors
    assert compiled.ignore_labels == expected_labels
    assert compiled.ignore_paths == expected_paths
    assert compiled.ignore_title_prefixes == expected_prefixes


@pytest.mark.asyncio
async def test_compile_noise_filters_defaults_to_noop_on_catalogue_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Operational catalogue errors result in a no-op CompiledNoiseFilters."""
    repo = make_repo_info()

    class _FailingCatalogueSessionFactory:
        def __call__(self) -> AsyncSession:
            statement = "SELECT 1"
            raise OperationalError(statement, {}, Exception("boom"))

    worker = GitHubIngestionWorker(
        session_factory,
        FakeGitHubClient(commits=[], pull_requests=[], issues=[], doc_changes=[]),
        catalogue_session_factory=typ.cast(
            "async_sessionmaker[AsyncSession]",
            _FailingCatalogueSessionFactory(),
        ),
    )
    compiled = await worker._compile_noise_filters(repo)
    assert compiled == CompiledNoiseFilters()
