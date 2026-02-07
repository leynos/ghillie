"""Behavioural coverage for scheduled reporting workflow."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

from pytest_bdd import given, scenario, then, when

from ghillie.bronze import RawEventWriter
from ghillie.evidence import EvidenceBundleService
from ghillie.gold import Report, ReportCoverage, ReportScope
from ghillie.reporting import ReportingConfig, ReportingService, ReportingWindow
from ghillie.silver import RawEventTransformer, Repository
from ghillie.status import MockStatusModel
from tests.helpers.event_builders import commit_envelope

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _build_reporting_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> ReportingService:
    """Build a configured ReportingService for tests.

    Parameters
    ----------
    session_factory
        Async session factory for database access.

    Returns
    -------
    ReportingService
        Configured service with EvidenceBundleService, MockStatusModel,
        and default test configuration.

    """
    evidence_service = EvidenceBundleService(session_factory)
    status_model = MockStatusModel()
    config = ReportingConfig(window_days=7)
    return ReportingService(
        session_factory=session_factory,
        evidence_service=evidence_service,
        status_model=status_model,
        config=config,
    )


class ReportingContext(typ.TypedDict, total=False):
    """Mutable context shared between steps."""

    session_factory: async_sessionmaker[AsyncSession]
    writer: RawEventWriter
    transformer: RawEventTransformer
    service: ReportingService
    repo_id: str
    report: Report | None
    window: ReportingWindow | None


@scenario("../reporting_workflow.feature", "Generate report for repository with events")
def test_generate_report_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


@scenario("../reporting_workflow.feature", "Window computation follows previous report")
def test_window_computation_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


@scenario("../reporting_workflow.feature", "Skip report when no events in window")
def test_skip_empty_window_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


@given(
    "an empty store with a repository containing events",
    target_fixture="reporting_context",
)
def given_repo_with_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> ReportingContext:
    """Set up a repository with events for reporting."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    service = _build_reporting_service(session_factory)

    context: ReportingContext = {
        "session_factory": session_factory,
        "writer": writer,
        "transformer": transformer,
        "service": service,
    }

    # Ingest some test events
    async def _setup() -> str:
        repo_slug = "octo/reef"
        commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)
        await writer.ingest(
            commit_envelope(repo_slug, "abc123", commit_time, "feat: new feature")
        )
        await transformer.process_pending()

        # Get repo ID
        from sqlalchemy import select

        async with session_factory() as session:
            repo = await session.scalar(select(Repository))
            assert repo is not None, "Repository should exist after event ingestion"
            return repo.id

    repo_id = asyncio.run(_setup())
    context["repo_id"] = repo_id
    return context


@given(
    "a repository with a previous report ending on July 7th",
    target_fixture="reporting_context",
)
def given_repo_with_previous_report(
    session_factory: async_sessionmaker[AsyncSession],
) -> ReportingContext:
    """Set up a repository with a previous report."""
    service = _build_reporting_service(session_factory)

    context: ReportingContext = {
        "session_factory": session_factory,
        "service": service,
    }

    async def _setup() -> str:
        # Create a repository
        async with session_factory() as session, session.begin():
            repo = Repository(
                github_owner="octo",
                github_name="reef",
                default_branch="main",
                ingestion_enabled=True,
            )
            session.add(repo)
            await session.flush()
            repo_id = repo.id

        # Create a previous report ending July 7th
        async with session_factory() as session, session.begin():
            report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=repo_id,
                window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 7, tzinfo=dt.UTC),
                model="mock-v1",
                human_text="Previous report",
            )
            session.add(report)

        return repo_id

    repo_id = asyncio.run(_setup())
    context["repo_id"] = repo_id
    return context


@given(
    "an empty store with a repository but no events",
    target_fixture="reporting_context",
)
def given_repo_without_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> ReportingContext:
    """Set up a repository without any events."""
    service = _build_reporting_service(session_factory)

    context: ReportingContext = {
        "session_factory": session_factory,
        "service": service,
    }

    async def _setup() -> str:
        async with session_factory() as session, session.begin():
            repo = Repository(
                github_owner="empty",
                github_name="repo",
                default_branch="main",
                ingestion_enabled=True,
            )
            session.add(repo)
            await session.flush()
            return repo.id

    repo_id = asyncio.run(_setup())
    context["repo_id"] = repo_id
    return context


@when("I run the reporting service for the repository")
def when_run_reporting_service(reporting_context: ReportingContext) -> None:
    """Run the reporting service for the repository."""

    async def _run() -> Report | None:
        service = reporting_context["service"]
        repo_id = reporting_context["repo_id"]
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        return await service.run_for_repository(repo_id, as_of=now)

    report = asyncio.run(_run())
    reporting_context["report"] = report


@when("I compute the next reporting window as of July 14th")
def when_compute_window(reporting_context: ReportingContext) -> None:
    """Compute the next reporting window."""

    async def _run() -> ReportingWindow:
        service = reporting_context["service"]
        repo_id = reporting_context["repo_id"]
        as_of = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        return await service.compute_next_window(repo_id, as_of=as_of)

    window = asyncio.run(_run())
    reporting_context["window"] = window


@then("a Gold report is created with the evidence bundle")
def then_report_created(reporting_context: ReportingContext) -> None:
    """Assert that a report was created."""
    report = reporting_context["report"]
    assert report is not None, "Report should be created"
    assert report.scope == ReportScope.REPOSITORY, "Report scope should be REPOSITORY"
    assert report.repository_id == reporting_context["repo_id"], (
        "Report repo ID mismatch"
    )
    assert report.human_text is not None, "Report should have human text"
    assert report.machine_summary is not None, "Report should have machine summary"


@then("the report links to the consumed event facts")
def then_report_links_events(reporting_context: ReportingContext) -> None:
    """Assert that the report has coverage records."""

    async def _assert() -> None:
        from sqlalchemy import select

        session_factory = reporting_context["session_factory"]
        report = reporting_context["report"]
        assert report is not None, "Report should exist before checking coverage"

        async with session_factory() as session:
            coverage = (
                await session.scalars(
                    select(ReportCoverage).where(ReportCoverage.report_id == report.id)
                )
            ).all()
            assert len(coverage) >= 1, "Report should have at least one coverage record"

    asyncio.run(_assert())


@then("the window starts on July 7th and ends on July 14th")
def then_window_correct(reporting_context: ReportingContext) -> None:
    """Assert the window computation is correct."""
    window = reporting_context["window"]
    assert window is not None, "Window should be computed"
    assert window.start == dt.datetime(2024, 7, 7, tzinfo=dt.UTC), (
        "Window should start July 7th"
    )
    assert window.end == dt.datetime(2024, 7, 14, tzinfo=dt.UTC), (
        "Window should end July 14th"
    )


@then("no report is generated")
def then_no_report(reporting_context: ReportingContext) -> None:
    """Assert that no report was generated."""
    report = reporting_context["report"]
    assert report is None, "No report should be generated when no events exist"
