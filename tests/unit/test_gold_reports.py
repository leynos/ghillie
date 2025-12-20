"""Unit coverage for Gold report metadata schema."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ghillie.bronze import RawEventEnvelope, RawEventWriter
from ghillie.common.slug import parse_repo_slug
from ghillie.gold import Report, ReportCoverage, ReportProject, ReportScope
from ghillie.silver import EventFact, RawEventTransformer, Repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _commit_event(
    repo_slug: str, commit_sha: str, occurred_at: dt.datetime
) -> RawEventEnvelope:
    """Create a minimal commit raw event envelope for coverage tests."""
    owner, name = parse_repo_slug(repo_slug)
    return RawEventEnvelope(
        source_system="github",
        source_event_id="commit-gold",
        event_type="github.commit",
        repo_external_id=repo_slug,
        occurred_at=occurred_at,
        payload={
            "sha": commit_sha,
            "message": "add gold schema",
            "author_email": "dev@example.com",
            "author_name": "Marina",
            "authored_at": "2024-07-06T10:00:00Z",
            "committed_at": "2024-07-06T10:05:00Z",
            "repo_owner": owner,
            "repo_name": name,
            "default_branch": "main",
            "metadata": {"ref": "refs/heads/main"},
        },
    )


@pytest.mark.asyncio
async def test_repository_report_persists_scope_and_coverage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repository-scoped reports link repositories and covered events."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    repo_slug = "octo/reef"
    commit_sha = "abc123"
    occurred_at = dt.datetime(2024, 7, 6, 10, 5, tzinfo=dt.UTC)

    await writer.ingest(_commit_event(repo_slug, commit_sha, occurred_at))
    await transformer.process_pending()

    async with session_factory() as session:
        repo = await session.scalar(select(Repository))
        assert repo is not None

        event_fact = await session.scalar(select(EventFact))
        assert event_fact is not None

        report = Report(
            scope=ReportScope.REPOSITORY,
            repository_id=repo.id,
            window_start=occurred_at - dt.timedelta(days=7),
            window_end=occurred_at,
            model="gpt-5.1-thinking",
            machine_summary={"status": "on_track"},
        )
        report.coverage_records.append(ReportCoverage(event_fact_id=event_fact.id))

        session.add(report)
        await session.commit()

        stored_report = await session.scalar(select(Report))
        assert stored_report is not None
        assert stored_report.scope is ReportScope.REPOSITORY
        assert stored_report.repository_id == repo.id
        assert stored_report.repository is repo
        assert stored_report.machine_summary["status"] == "on_track"

        coverage = await session.scalar(select(ReportCoverage))
        assert coverage is not None
        assert coverage.report_id == stored_report.id
        assert coverage.event_fact_id == event_fact.id


@pytest.mark.asyncio
async def test_project_report_requires_project_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Project-scoped reports validate that a project is linked."""
    async with session_factory() as session:
        project = ReportProject(key="wildside", name="Wildside")
        session.add(project)
        await session.flush()

        report = Report(
            scope=ReportScope.PROJECT,
            project_id=project.id,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            model="gpt-5.1-mini",
            machine_summary={},
        )
        session.add(report)
        await session.commit()

        stored = await session.scalar(
            select(Report).where(Report.project_id == project.id)
        )
        assert stored is not None
        assert stored.project is project

        reports = (
            await session.scalars(select(Report).where(Report.project_id == project.id))
        ).all()
        assert reports == [stored]


@pytest.mark.asyncio
async def test_repository_scope_without_repo_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Scope constraints reject repository reports without a repository link."""
    async with session_factory() as session:
        report = Report(
            scope=ReportScope.REPOSITORY,
            repository_id=None,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            model="gpt-5.1-thinking",
            machine_summary={},
        )
        session.add(report)

        with pytest.raises(IntegrityError):
            await session.commit()

        await session.rollback()
