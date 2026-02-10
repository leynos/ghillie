"""Unit tests for ReportingService window computation."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest

from ghillie.gold import Report, ReportScope
from tests.unit.conftest import create_test_repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.reporting.service import ReportingService


class TestReportingServiceWindowComputation:
    """Tests for window computation in ReportingService."""

    @pytest.mark.asyncio
    async def test_computes_window_from_last_report(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reporting_service: ReportingService,
    ) -> None:
        """Next window starts where last report ended."""
        repo_id = await create_test_repository(session_factory)

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
        repo_id = await create_test_repository(session_factory)
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)

        window = await reporting_service.compute_next_window(repo_id, as_of=now)

        expected_start = now - dt.timedelta(days=7)
        assert window.start == expected_start, "Window should start 7 days before as_of"
        assert window.end == now, "Window should end at as_of time"
