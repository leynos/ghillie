"""Unit tests for ReportingService."""

from __future__ import annotations

import datetime as dt
import typing as typ
from pathlib import Path

import pytest
import pytest_asyncio

from ghillie.bronze import RawEventWriter
from ghillie.evidence import EvidenceBundleService
from ghillie.gold import Report, ReportCoverage, ReportScope
from ghillie.reporting.config import ReportingConfig
from ghillie.reporting.filesystem_sink import FilesystemReportSink
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


async def _create_repository(
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


async def _get_repo_id(
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
        assert repo is not None, f"Repository {owner}/{name} not found"
        return repo.id


@pytest_asyncio.fixture
async def generated_report(
    session_factory: async_sessionmaker[AsyncSession],
    reporting_service: ReportingService,
    writer: RawEventWriter,
    transformer: RawEventTransformer,
) -> tuple[Report, str]:
    """Generate a standard test report and return (report, repo_id).

    Sets up standard test data:
    - repo_slug: acme/widget
    - window: 2024-07-01 to 2024-07-08
    - commit at 2024-07-05 10:00 UTC with hash "abc123"
    """
    repo_slug = "acme/widget"
    window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
    window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)
    commit_time = dt.datetime(2024, 7, 5, 10, 0, tzinfo=dt.UTC)

    await writer.ingest(
        commit_envelope(repo_slug, "abc123", commit_time, "feat: new feature")
    )
    await transformer.process_pending()

    repo_id = await _get_repo_id(session_factory)

    report = await reporting_service.generate_report(
        repository_id=repo_id,
        window_start=window_start,
        window_end=window_end,
    )

    return report, repo_id


class TestReportingConfig:
    """Tests for ReportingConfig dataclass."""

    def test_default_window_days(self) -> None:
        """Default window is 7 days."""
        config = ReportingConfig()
        assert config.window_days == 7, "Default window should be 7 days"

    def test_custom_window_days(self) -> None:
        """Window days can be customized."""
        config = ReportingConfig(window_days=14)
        assert config.window_days == 14, "Custom window days not applied"

    def test_from_env_uses_defaults_when_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """from_env returns defaults when env vars are unset."""
        monkeypatch.delenv("GHILLIE_REPORTING_WINDOW_DAYS", raising=False)
        monkeypatch.delenv("GHILLIE_REPORT_SINK_PATH", raising=False)
        config = ReportingConfig.from_env()
        assert config.window_days == 7, "Default window should be 7 when env unset"

    def test_from_env_reads_window_days(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """from_env reads GHILLIE_REPORTING_WINDOW_DAYS."""
        monkeypatch.setenv("GHILLIE_REPORTING_WINDOW_DAYS", "30")
        monkeypatch.delenv("GHILLIE_REPORT_SINK_PATH", raising=False)
        config = ReportingConfig.from_env()
        assert config.window_days == 30, "Window days should read from env"

    def test_config_report_sink_path_defaults_to_none(self) -> None:
        """The report_sink_path field defaults to None."""
        config = ReportingConfig()
        assert config.report_sink_path is None, (
            "report_sink_path should default to None"
        )

    def test_config_from_env_reads_report_sink_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GHILLIE_REPORT_SINK_PATH is read and stored as a Path."""
        monkeypatch.delenv("GHILLIE_REPORTING_WINDOW_DAYS", raising=False)
        monkeypatch.setenv("GHILLIE_REPORT_SINK_PATH", "/var/lib/ghillie/reports")
        config = ReportingConfig.from_env()
        assert config.report_sink_path == Path("/var/lib/ghillie/reports"), (
            "report_sink_path should be parsed from environment"
        )

    def test_config_from_env_report_sink_path_unset_yields_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When GHILLIE_REPORT_SINK_PATH is unset, report_sink_path is None."""
        monkeypatch.delenv("GHILLIE_REPORTING_WINDOW_DAYS", raising=False)
        monkeypatch.delenv("GHILLIE_REPORT_SINK_PATH", raising=False)
        config = ReportingConfig.from_env()
        assert config.report_sink_path is None, (
            "report_sink_path should be None when env var unset"
        )


class TestReportingServiceWindowComputation:
    """Tests for window computation in ReportingService."""

    @pytest.mark.asyncio
    async def test_computes_window_from_last_report(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reporting_service: ReportingService,
    ) -> None:
        """Next window starts where last report ended."""
        repo_id = await _create_repository(session_factory)

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

        assert window.start == previous_end, (
            "Window should start at previous report end"
        )
        assert window.end == now, "Window should end at as_of time"

    @pytest.mark.asyncio
    async def test_computes_window_with_no_previous_report(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reporting_service: ReportingService,
    ) -> None:
        """When no previous report exists, window starts window_days ago."""
        repo_id = await _create_repository(session_factory)
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)

        window = await reporting_service.compute_next_window(repo_id, as_of=now)

        expected_start = now - dt.timedelta(days=7)
        assert window.start == expected_start, "Window should start 7 days before as_of"
        assert window.end == now, "Window should end at as_of time"


class TestReportingServiceGenerateReport:
    """Tests for report generation in ReportingService."""

    @pytest.mark.asyncio
    async def test_generates_report_for_repository(
        self,
        generated_report: tuple[Report, str],
    ) -> None:
        """Generates a report and persists it to the Gold layer."""
        report, repo_id = generated_report
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        assert report.scope == ReportScope.REPOSITORY, (
            "Report scope should be REPOSITORY"
        )
        assert report.repository_id == repo_id, (
            "Report should reference correct repository"
        )
        assert report.window_start == window_start, "Report window_start mismatch"
        assert report.window_end == window_end, "Report window_end mismatch"
        assert report.model == "mock-v1", "Report model should be mock-v1"
        assert report.human_text is not None, "Report should have human text"
        assert "status" in report.machine_summary, (
            "Machine summary should contain status"
        )

    @pytest.mark.asyncio
    async def test_creates_coverage_records(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        generated_report: tuple[Report, str],
    ) -> None:
        """Report generation creates coverage records linking events to report."""
        report, _repo_id = generated_report

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
        assert coverage_count >= 1, "At least one coverage record should exist"

    @pytest.mark.asyncio
    async def test_report_persisted_to_database(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        generated_report: tuple[Report, str],
    ) -> None:
        """Generated report is persisted and can be queried."""
        report, repo_id = generated_report

        async with session_factory() as session:
            fetched = await session.get(Report, report.id)
            assert fetched is not None, "Report should be persisted to database"
            assert fetched.repository_id == repo_id, (
                "Persisted report should match repo"
            )


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

        repo_id = await _get_repo_id(session_factory)

        report = await reporting_service.run_for_repository(repo_id, as_of=now)

        assert report is not None, "Report should be generated"
        assert report.repository_id == repo_id, (
            "Report should reference correct repository"
        )
        assert report.window_end == now, "Report window_end should match as_of"

    @pytest.mark.asyncio
    async def test_run_skips_empty_window(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reporting_service: ReportingService,
    ) -> None:
        """run_for_repository returns None when no events exist in window."""
        repo_id = await _create_repository(session_factory)
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)

        result = await reporting_service.run_for_repository(repo_id, as_of=now)

        # May return None or a report with empty bundle - implementation choice
        # For now, expect None when there are no events
        assert result is None, "Should return None when no events in window"


class TestReportingServiceSinkIntegration:
    """Tests for ReportSink integration in ReportingService."""

    @pytest.mark.asyncio
    async def test_generate_report_calls_sink_when_provided(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        writer: RawEventWriter,
        transformer: RawEventTransformer,
        tmp_path: Path,
    ) -> None:
        """When a ReportSink is injected, write_report is called."""
        sink = FilesystemReportSink(tmp_path / "reports")
        evidence_service = EvidenceBundleService(session_factory)
        service = ReportingService(
            session_factory=session_factory,
            evidence_service=evidence_service,
            status_model=MockStatusModel(),
            report_sink=sink,
        )

        repo_slug = "acme/widget"
        commit_time = dt.datetime(2024, 7, 5, 10, 0, tzinfo=dt.UTC)
        await writer.ingest(
            commit_envelope(repo_slug, "sink001", commit_time, "feat: sink test")
        )
        await transformer.process_pending()

        repo_id = await _get_repo_id(session_factory)

        await service.generate_report(
            repository_id=repo_id,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        )

        latest = tmp_path / "reports" / "acme" / "widget" / "latest.md"
        assert latest.is_file(), "Sink should write latest.md after report generation"

    @pytest.mark.asyncio
    async def test_generate_report_works_without_sink(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        writer: RawEventWriter,
        transformer: RawEventTransformer,
        tmp_path: Path,
    ) -> None:
        """When no sink is provided, report generation succeeds."""
        evidence_service = EvidenceBundleService(session_factory)
        service = ReportingService(
            session_factory=session_factory,
            evidence_service=evidence_service,
            status_model=MockStatusModel(),
        )

        repo_slug = "acme/widget"
        commit_time = dt.datetime(2024, 7, 5, 10, 0, tzinfo=dt.UTC)
        await writer.ingest(
            commit_envelope(repo_slug, "nosink1", commit_time, "feat: no sink")
        )
        await transformer.process_pending()

        repo_id = await _get_repo_id(session_factory)

        report = await service.generate_report(
            repository_id=repo_id,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        )
        assert report is not None, "Report should be generated without a sink"

    @pytest.mark.asyncio
    async def test_run_for_repository_calls_sink_when_provided(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        writer: RawEventWriter,
        transformer: RawEventTransformer,
        tmp_path: Path,
    ) -> None:
        """run_for_repository also invokes the sink."""
        sink = FilesystemReportSink(tmp_path / "reports")
        evidence_service = EvidenceBundleService(session_factory)
        service = ReportingService(
            session_factory=session_factory,
            evidence_service=evidence_service,
            status_model=MockStatusModel(),
            report_sink=sink,
        )

        repo_slug = "acme/widget"
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)
        await writer.ingest(
            commit_envelope(repo_slug, "run001", commit_time, "feat: run sink")
        )
        await transformer.process_pending()

        repo_id = await _get_repo_id(session_factory)
        report = await service.run_for_repository(repo_id, as_of=now)

        assert report is not None, "Report should be generated"
        latest = tmp_path / "reports" / "acme" / "widget" / "latest.md"
        assert latest.is_file(), "Sink should write latest.md via run_for_repository"
