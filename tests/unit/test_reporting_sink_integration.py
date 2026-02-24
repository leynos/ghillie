"""Unit tests for ReportSink integration in ReportingService."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest

from ghillie.evidence import EvidenceBundleService
from ghillie.reporting.filesystem_sink import FilesystemReportSink
from ghillie.reporting.service import ReportingService, ReportingServiceDependencies
from ghillie.status import MockStatusModel
from tests.fixtures.specs import RepositoryEventSpec
from tests.unit.conftest import setup_test_repository_with_event

if typ.TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.bronze import RawEventWriter
    from ghillie.silver import RawEventTransformer


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
        deps = ReportingServiceDependencies(
            session_factory=session_factory,
            evidence_service=EvidenceBundleService(session_factory),
            status_model=MockStatusModel(),
        )
        service = ReportingService(deps, report_sink=sink)

        repo_id = await setup_test_repository_with_event(
            writer,
            transformer,
            session_factory,
            spec=RepositoryEventSpec(commit_hash="sink001"),
        )

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
    ) -> None:
        """When no sink is provided, report generation succeeds."""
        deps = ReportingServiceDependencies(
            session_factory=session_factory,
            evidence_service=EvidenceBundleService(session_factory),
            status_model=MockStatusModel(),
        )
        service = ReportingService(deps)

        repo_id = await setup_test_repository_with_event(
            writer,
            transformer,
            session_factory,
            spec=RepositoryEventSpec(commit_hash="nosink1"),
        )

        report = await service.generate_report(
            repository_id=repo_id,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        )
        assert report is not None, "Report should be generated without a sink"

    @pytest.mark.asyncio
    async def test_generate_report_skips_sink_when_repository_deleted(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        writer: RawEventWriter,
        transformer: RawEventTransformer,
        tmp_path: Path,
    ) -> None:
        """Sink write is skipped when the repository is deleted."""
        from sqlalchemy import delete as sa_delete

        from ghillie.silver import Repository

        sink = FilesystemReportSink(tmp_path / "reports")
        deps = ReportingServiceDependencies(
            session_factory=session_factory,
            evidence_service=EvidenceBundleService(session_factory),
            status_model=MockStatusModel(),
        )
        service = ReportingService(deps, report_sink=sink)

        repo_id = await setup_test_repository_with_event(
            writer,
            transformer,
            session_factory,
            spec=RepositoryEventSpec(commit_hash="del001"),
        )

        # Build the evidence bundle while the repo still exists.
        bundle = await deps.evidence_service.build_bundle(
            repository_id=repo_id,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        )

        # Delete the repository so _write_to_sink cannot look it up.
        async with session_factory() as session, session.begin():
            await session.execute(sa_delete(Repository).where(Repository.id == repo_id))

        # generate_report should succeed; the sink write is silently skipped.
        report = await service.generate_report(
            repository_id=repo_id,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            bundle=bundle,
        )
        assert report is not None, "Report should still be generated"

        reports_dir = tmp_path / "reports"
        if reports_dir.exists():
            written_files = list(reports_dir.rglob("*.md"))
            assert written_files == [], (
                "No Markdown files should be written when repository is missing"
            )

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
        deps = ReportingServiceDependencies(
            session_factory=session_factory,
            evidence_service=EvidenceBundleService(session_factory),
            status_model=MockStatusModel(),
        )
        service = ReportingService(deps, report_sink=sink)

        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        repo_id = await setup_test_repository_with_event(
            writer,
            transformer,
            session_factory,
            spec=RepositoryEventSpec(
                commit_hash="run001",
                commit_time=dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC),
            ),
        )
        report = await service.run_for_repository(repo_id, as_of=now)

        assert report is not None, "Report should be generated"
        latest = tmp_path / "reports" / "acme" / "widget" / "latest.md"
        assert latest.is_file(), "Sink should write latest.md via run_for_repository"
