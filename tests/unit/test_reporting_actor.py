"""Unit tests for the reporting Dramatiq actor."""

from __future__ import annotations

import dataclasses
import datetime as dt
import typing as typ

import pytest

from ghillie.bronze import RawEventWriter
from ghillie.gold import Report
from ghillie.silver import RawEventTransformer, Repository
from ghillie.status import MockStatusModel
from tests.helpers.event_builders import commit_envelope

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclasses.dataclass
class RepositoryConfig:
    """Configuration for creating a test repository."""

    owner: str
    name: str
    estate_id: str
    ingestion_enabled: bool = True
    default_branch: str = "main"


async def create_repository_with_estate(
    session_factory: async_sessionmaker[AsyncSession],
    config: RepositoryConfig,
) -> str:
    """Create a test repository and return its ID."""
    async with session_factory() as session, session.begin():
        repo = Repository(
            github_owner=config.owner,
            github_name=config.name,
            default_branch=config.default_branch,
            ingestion_enabled=config.ingestion_enabled,
            estate_id=config.estate_id,
        )
        session.add(repo)
        await session.flush()
        return repo.id


async def get_repo_id(
    session_factory: async_sessionmaker[AsyncSession],
    owner: str,
    name: str,
) -> str:
    """Query repository by owner/name and return its ID."""
    from sqlalchemy import select

    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == owner,
                Repository.github_name == name,
            )
        )
        assert repo is not None
        return repo.id


async def count_reports(
    session_factory: async_sessionmaker[AsyncSession],
    repository_id: str,
) -> int:
    """Count reports for a repository."""
    from sqlalchemy import func, select

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Report)
            .where(Report.repository_id == repository_id)
        )
        return count or 0


class TestGenerateReportJob:
    """Tests for the generate_report_job Dramatiq actor."""

    @pytest.mark.asyncio
    async def test_generates_report_for_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Actor generates a report for a repository with events."""
        repo_slug = "test/repo"
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)

        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)

        await writer.ingest(
            commit_envelope(repo_slug, "abc123", commit_time, "feat: feature")
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory, "test", "repo")

        # For testing, we call the underlying async function with MockStatusModel
        from ghillie.reporting.actor import _generate_report_async

        result = await _generate_report_async(
            session_factory=session_factory,
            repository_id=repo_id,
            as_of=now,
            status_model=MockStatusModel(),
        )

        assert result is not None
        assert result.repository_id == repo_id

    @pytest.mark.asyncio
    async def test_skips_repository_with_no_events(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Actor returns None when no events exist in window."""
        repo_id = await create_repository_with_estate(
            session_factory,
            RepositoryConfig(owner="empty", name="repo", estate_id="estate-1"),
        )
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)

        from ghillie.reporting.actor import _generate_report_async

        result = await _generate_report_async(
            session_factory=session_factory,
            repository_id=repo_id,
            as_of=now,
            status_model=MockStatusModel(),
        )

        assert result is None


class TestGenerateReportsForEstateJob:
    """Tests for the generate_reports_for_estate_job Dramatiq actor."""

    @pytest.mark.asyncio
    async def test_generates_reports_for_all_active_repositories(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Actor generates reports for all active repositories in estate."""
        estate_id = "estate-alpha"
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)

        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)

        # Create two repositories in the same estate
        await writer.ingest(
            commit_envelope("alpha/one", "sha1", commit_time, "feat: one")
        )
        await writer.ingest(
            commit_envelope("alpha/two", "sha2", commit_time, "fix: two")
        )
        await transformer.process_pending()

        # Set estate_id on both repos
        from sqlalchemy import select

        async with session_factory() as session, session.begin():
            repos = (await session.scalars(select(Repository))).all()
            for repo in repos:
                repo.estate_id = estate_id
                repo.ingestion_enabled = True

        from ghillie.reporting.actor import _generate_reports_for_estate_async

        results = await _generate_reports_for_estate_async(
            session_factory=session_factory,
            estate_id=estate_id,
            as_of=now,
            status_model=MockStatusModel(),
        )

        assert len(results) == 2
        assert all(r is not None for r in results)

    @pytest.mark.asyncio
    async def test_skips_inactive_repositories(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Actor skips repositories with ingestion_enabled=False."""
        estate_id = "estate-beta"
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)

        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)

        await writer.ingest(
            commit_envelope("beta/active", "sha1", commit_time, "feat: active")
        )
        await writer.ingest(
            commit_envelope("beta/inactive", "sha2", commit_time, "fix: inactive")
        )
        await transformer.process_pending()

        async with session_factory() as session, session.begin():
            from sqlalchemy import select

            repos = (await session.scalars(select(Repository))).all()
            for repo in repos:
                repo.estate_id = estate_id
                if "inactive" in repo.github_name:
                    repo.ingestion_enabled = False
                else:
                    repo.ingestion_enabled = True

        from ghillie.reporting.actor import _generate_reports_for_estate_async

        results = await _generate_reports_for_estate_async(
            session_factory=session_factory,
            estate_id=estate_id,
            as_of=now,
            status_model=MockStatusModel(),
        )

        # Only the active repository should have a report
        non_none_results = [r for r in results if r is not None]
        assert len(non_none_results) == 1
