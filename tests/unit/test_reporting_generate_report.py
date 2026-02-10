"""Unit tests for ReportingService report generation."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest

from ghillie.gold import Report, ReportCoverage, ReportScope

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TestReportingServiceGenerateReport:
    """Tests for report generation in ReportingService."""

    @pytest.mark.asyncio
    async def test_generates_report_for_repository(
        self,
        generated_report: tuple[Report, str],
    ) -> None:
        """Generate a report and persist it to the Gold layer."""
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
        """Generate report is persisted and can be queried."""
        report, repo_id = generated_report

        async with session_factory() as session:
            fetched = await session.get(Report, report.id)
            assert fetched is not None, "Report should be persisted to database"
            assert fetched.repository_id == repo_id, (
                "Persisted report should match repo"
            )
