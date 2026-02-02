"""Unit tests for ReportingService."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest

from ghillie.bronze import RawEventWriter
from ghillie.evidence import EvidenceBundleService
from ghillie.gold import Report, ReportCoverage, ReportScope
from ghillie.reporting.config import ReportingConfig
from ghillie.reporting.service import ReportingService
from ghillie.silver import RawEventTransformer, Repository
from ghillie.status import MockStatusModel
from tests.helpers.event_builders import commit_envelope

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reporting_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> ReportingService:
    """Return a configured ReportingService for testing."""
    evidence_service = EvidenceBundleService(session_factory)
    status_model = MockStatusModel()
    config = ReportingConfig()
    return ReportingService(
        session_factory=session_factory,
        evidence_service=evidence_service,
        status_model=status_model,
        config=config,
    )


@pytest.fixture
def writer(
    session_factory: async_sessionmaker[AsyncSession],
) -> RawEventWriter:
    """Return a RawEventWriter for test data setup."""
    return RawEventWriter(session_factory)


@pytest.fixture
def transformer(
    session_factory: async_sessionmaker[AsyncSession],
) -> RawEventTransformer:
    """Return a RawEventTransformer for test data setup."""
    return RawEventTransformer(session_factory)


async def create_repository(
    session_factory: async_sessionmaker[AsyncSession],
    owner: str = "acme",
    name: str = "widget",
) -> str:
    """Create a test repository and return its ID."""
    async with session_factory() as session, session.begin():
        repo = Repository(
            github_owner=owner,
            github_name=name,
            default_branch="main",
            ingestion_enabled=True,
            estate_id="estate-1",
        )
        session.add(repo)
        await session.flush()
        return repo.id


async def get_repo_id(
    session_factory: async_sessionmaker[AsyncSession],
    owner: str = "acme",
    name: str = "widget",
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


class TestReportingConfig:
    """Tests for ReportingConfig dataclass."""

    def test_default_window_days(self) -> None:
        """Default window is 7 days."""
        config = ReportingConfig()
        assert config.window_days == 7

    def test_custom_window_days(self) -> None:
        """Window days can be customised."""
        config = ReportingConfig(window_days=14)
        assert config.window_days == 14

    def test_from_env_uses_defaults_when_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """from_env returns defaults when env vars are unset."""
        monkeypatch.delenv("GHILLIE_REPORTING_WINDOW_DAYS", raising=False)
        config = ReportingConfig.from_env()
        assert config.window_days == 7

    def test_from_env_reads_window_days(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """from_env reads GHILLIE_REPORTING_WINDOW_DAYS."""
        monkeypatch.setenv("GHILLIE_REPORTING_WINDOW_DAYS", "30")
        config = ReportingConfig.from_env()
        assert config.window_days == 30


class TestReportingServiceWindowComputation:
    """Tests for window computation in ReportingService."""

    @pytest.mark.asyncio
    async def test_computes_window_from_last_report(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reporting_service: ReportingService,
    ) -> None:
        """Next window starts where last report ended."""
        repo_id = await create_repository(session_factory)

        # Create a previous report
        previous_end = dt.datetime(2024, 7, 7, tzinfo=dt.UTC)
        async with session_factory() as session, session.begin():
            report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=repo_id,
                window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                window_end=previous_end,
            )
            session.add(report)

        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        window = await reporting_service.compute_next_window(repo_id, as_of=now)

        assert window.start == previous_end
        assert window.end == now

    @pytest.mark.asyncio
    async def test_computes_window_with_no_previous_report(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reporting_service: ReportingService,
    ) -> None:
        """When no previous report exists, window starts window_days ago."""
        repo_id = await create_repository(session_factory)
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)

        window = await reporting_service.compute_next_window(repo_id, as_of=now)

        expected_start = now - dt.timedelta(days=7)
        assert window.start == expected_start
        assert window.end == now


class TestReportingServiceGenerateReport:
    """Tests for report generation in ReportingService."""

    @pytest.mark.asyncio
    async def test_generates_report_for_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reporting_service: ReportingService,
        writer: RawEventWriter,
        transformer: RawEventTransformer,
    ) -> None:
        """Generates a report and persists it to the Gold layer."""
        repo_slug = "acme/widget"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)
        commit_time = dt.datetime(2024, 7, 5, 10, 0, tzinfo=dt.UTC)

        # Ingest test data
        await writer.ingest(
            commit_envelope(repo_slug, "abc123", commit_time, "feat: new feature")
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)

        report = await reporting_service.generate_report(
            repository_id=repo_id,
            window_start=window_start,
            window_end=window_end,
        )

        assert report.scope == ReportScope.REPOSITORY
        assert report.repository_id == repo_id
        assert report.window_start == window_start
        assert report.window_end == window_end
        assert report.model == "mock-v1"
        assert report.human_text is not None
        assert "status" in report.machine_summary

    @pytest.mark.asyncio
    async def test_creates_coverage_records(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reporting_service: ReportingService,
        writer: RawEventWriter,
        transformer: RawEventTransformer,
    ) -> None:
        """Report generation creates coverage records linking events to report."""
        repo_slug = "acme/widget"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)
        commit_time = dt.datetime(2024, 7, 5, 10, 0, tzinfo=dt.UTC)

        await writer.ingest(
            commit_envelope(repo_slug, "def456", commit_time, "fix: bug fix")
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)

        report = await reporting_service.generate_report(
            repository_id=repo_id,
            window_start=window_start,
            window_end=window_end,
        )

        # Verify coverage records exist
        from sqlalchemy import select

        async with session_factory() as session:
            coverage_count = len(
                (
                    await session.scalars(
                        select(ReportCoverage).where(
                            ReportCoverage.report_id == report.id
                        )
                    )
                ).all()
            )
        assert coverage_count >= 1

    @pytest.mark.asyncio
    async def test_report_persisted_to_database(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reporting_service: ReportingService,
        writer: RawEventWriter,
        transformer: RawEventTransformer,
    ) -> None:
        """Generated report is persisted and can be queried."""
        repo_slug = "acme/widget"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)
        commit_time = dt.datetime(2024, 7, 5, 10, 0, tzinfo=dt.UTC)

        await writer.ingest(
            commit_envelope(repo_slug, "ghi789", commit_time, "chore: maintenance")
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)
        report = await reporting_service.generate_report(
            repository_id=repo_id,
            window_start=window_start,
            window_end=window_end,
        )

        # Fetch from database
        async with session_factory() as session:
            fetched = await session.get(Report, report.id)
            assert fetched is not None
            assert fetched.repository_id == repo_id


class TestReportingServiceRunForRepository:
    """Tests for full reporting workflow via run_for_repository."""

    @pytest.mark.asyncio
    async def test_run_generates_report_with_computed_window(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reporting_service: ReportingService,
        writer: RawEventWriter,
        transformer: RawEventTransformer,
    ) -> None:
        """run_for_repository computes window and generates report."""
        repo_slug = "acme/widget"
        # Place commit within the 7-day window ending at 'now'
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)

        await writer.ingest(
            commit_envelope(repo_slug, "jkl012", commit_time, "feat: another feature")
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)

        report = await reporting_service.run_for_repository(repo_id, as_of=now)

        assert report is not None
        assert report.repository_id == repo_id
        assert report.window_end == now

    @pytest.mark.asyncio
    async def test_run_skips_empty_window(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reporting_service: ReportingService,
    ) -> None:
        """run_for_repository returns None when no events exist in window."""
        repo_id = await create_repository(session_factory)
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)

        result = await reporting_service.run_for_repository(repo_id, as_of=now)

        # May return None or a report with empty bundle - implementation choice
        # For now, expect None when there are no events
        assert result is None
