"""Unit tests for ReportingService.run_for_repository."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest

from tests.helpers.event_builders import commit_envelope
from tests.unit.conftest import create_test_repository, get_repo_id

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.bronze import RawEventWriter
    from ghillie.reporting.service import ReportingService
    from ghillie.silver import RawEventTransformer


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
        repo_id = await create_test_repository(session_factory)
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)

        result = await reporting_service.run_for_repository(repo_id, as_of=now)

        # May return None or a report with empty bundle - implementation choice
        # For now, expect None when there are no events
        assert result is None, "Should return None when no events in window"
