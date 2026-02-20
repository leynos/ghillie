"""Unit tests for reporting metrics aggregation queries.

This module verifies period and estate-level aggregation behaviour for report
counts, latency profiles, and token totals in ``ReportingMetricsService``.

Usage
-----
Run this module directly while iterating on metrics query logic:

>>> # uv run pytest tests/unit/test_reporting_metrics_service.py -v

"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import typing as typ

import pytest

from ghillie.gold import Report, ReportScope
from ghillie.reporting.metrics_service import ReportingMetricsService
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _create_repository(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner: str,
    name: str,
    estate_id: str,
) -> str:
    """Insert a repository row and return its ID."""
    async with session_factory() as session, session.begin():
        repo = Repository(
            github_owner=owner,
            github_name=name,
            default_branch="main",
            ingestion_enabled=True,
            estate_id=estate_id,
        )
        session.add(repo)
        await session.flush()
        return repo.id


@dc.dataclass(frozen=True, slots=True)
class ReportInsertSpec:
    """Parameters for inserting a report row in aggregation tests."""

    repository_id: str
    generated_at: dt.datetime
    model_latency_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


async def _create_report(
    session_factory: async_sessionmaker[AsyncSession],
    spec: ReportInsertSpec,
) -> None:
    """Insert a repository-scoped report with optional metrics."""
    async with session_factory() as session, session.begin():
        report = Report(
            scope=ReportScope.REPOSITORY,
            repository_id=spec.repository_id,
            window_start=spec.generated_at - dt.timedelta(days=7),
            window_end=spec.generated_at,
            generated_at=spec.generated_at,
            model="mock-v1",
            human_text="summary",
            machine_summary={"status": "on_track"},
            model_latency_ms=spec.model_latency_ms,
            prompt_tokens=spec.prompt_tokens,
            completion_tokens=spec.completion_tokens,
            total_tokens=spec.total_tokens,
        )
        session.add(report)


async def _create_period_test_fixture(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Create one repository and four reports for period aggregation tests."""
    repo_id = await _create_repository(
        session_factory,
        owner="acme",
        name="widget",
        estate_id="estate-a",
    )

    inside_1 = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)
    inside_2 = dt.datetime(2024, 7, 9, tzinfo=dt.UTC)
    inside_3 = dt.datetime(2024, 7, 10, tzinfo=dt.UTC)
    outside = dt.datetime(2024, 6, 20, tzinfo=dt.UTC)

    await _create_report(
        session_factory,
        ReportInsertSpec(
            repository_id=repo_id,
            generated_at=inside_1,
            model_latency_ms=100,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )
    await _create_report(
        session_factory,
        ReportInsertSpec(
            repository_id=repo_id,
            generated_at=inside_2,
            model_latency_ms=300,
            prompt_tokens=30,
            completion_tokens=20,
            total_tokens=50,
        ),
    )
    await _create_report(
        session_factory,
        ReportInsertSpec(
            repository_id=repo_id,
            generated_at=inside_3,
            model_latency_ms=None,
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
        ),
    )
    await _create_report(
        session_factory,
        ReportInsertSpec(
            repository_id=repo_id,
            generated_at=outside,
            model_latency_ms=700,
            prompt_tokens=70,
            completion_tokens=20,
            total_tokens=90,
        ),
    )

    return repo_id


class TestReportingMetricsService:
    """Tests for period and estate-level reporting metrics snapshots."""

    @pytest.mark.asyncio
    async def test_period_metrics_empty_returns_zeros(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """No reports in period yields zero totals and empty latency profile."""
        service = ReportingMetricsService(session_factory)
        period_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        period_end = dt.datetime(2024, 7, 31, tzinfo=dt.UTC)

        snapshot = await service.get_metrics_for_period(period_start, period_end)

        assert snapshot.total_reports == 0, (
            "Expected zero reports when no rows exist in the selected period"
        )
        assert snapshot.reports_with_metrics == 0, (
            "Expected zero reports_with_metrics when no rows exist in period"
        )
        assert snapshot.avg_latency_ms is None, (
            "Expected average latency to be None without latency data"
        )
        assert snapshot.p95_latency_ms is None, (
            "Expected p95 latency to be None without latency data"
        )
        assert snapshot.total_prompt_tokens == 0, (
            "Expected prompt token total to be zero when no reports exist"
        )
        assert snapshot.total_completion_tokens == 0, (
            "Expected completion token total to be zero when no reports exist"
        )
        assert snapshot.total_tokens == 0, (
            "Expected total token usage to be zero when no reports exist"
        )

    @pytest.mark.asyncio
    async def test_period_metrics_aggregate_counts_latency_and_tokens(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Service aggregates totals and latency profile for a time window."""
        await _create_period_test_fixture(session_factory)
        service = ReportingMetricsService(session_factory)
        period_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        period_end = dt.datetime(2024, 8, 1, tzinfo=dt.UTC)

        snapshot = await service.get_metrics_for_period(period_start, period_end)

        assert snapshot.total_reports == 3, (
            "Expected three July reports and exclusion of the out-of-period row"
        )
        assert snapshot.reports_with_metrics == 2, (
            "Expected reports_with_metrics to count only rows with non-null metrics"
        )
        assert snapshot.avg_latency_ms == 200.0, (
            "Expected average latency from 100 ms and 300 ms rows"
        )
        assert snapshot.p95_latency_ms == 300.0, (
            "Expected p95 latency to resolve to the highest latency in sample"
        )
        assert snapshot.total_prompt_tokens == 40, (
            "Expected prompt token total from in-period rows only"
        )
        assert snapshot.total_completion_tokens == 25, (
            "Expected completion token total from in-period rows only"
        )
        assert snapshot.total_tokens == 65, (
            "Expected total token count from in-period rows only"
        )

    @pytest.mark.asyncio
    async def test_partial_token_metrics_count_as_metrics_and_total_fallback(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Rows with token metrics only still count and contribute to totals."""
        repo_id = await _create_repository(
            session_factory,
            owner="acme",
            name="widget",
            estate_id="estate-a",
        )
        generated_at = dt.datetime(2024, 7, 12, tzinfo=dt.UTC)
        await _create_report(
            session_factory,
            ReportInsertSpec(
                repository_id=repo_id,
                generated_at=generated_at,
                model_latency_ms=None,
                prompt_tokens=7,
                completion_tokens=3,
                total_tokens=None,
            ),
        )

        service = ReportingMetricsService(session_factory)
        period_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        period_end = dt.datetime(2024, 8, 1, tzinfo=dt.UTC)
        snapshot = await service.get_metrics_for_period(period_start, period_end)

        assert snapshot.total_reports == 1, (
            "Expected one report in period for partial-token metrics fixture"
        )
        assert snapshot.reports_with_metrics == 1, (
            "Expected token-only metrics row to count as report with metrics"
        )
        assert snapshot.avg_latency_ms is None, (
            "Expected average latency to be None when latency is missing"
        )
        assert snapshot.p95_latency_ms is None, (
            "Expected p95 latency to be None when latency is missing"
        )
        assert snapshot.total_prompt_tokens == 7, (
            "Expected prompt token total to include token-only metrics row"
        )
        assert snapshot.total_completion_tokens == 3, (
            "Expected completion token total to include token-only metrics row"
        )
        assert snapshot.total_tokens == 10, (
            "Expected total token fallback to sum prompt and completion tokens"
        )

    @pytest.mark.asyncio
    async def test_period_end_before_start_raises_value_error(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Invalid period bounds raise a clear ``ValueError``."""
        service = ReportingMetricsService(session_factory)

        with pytest.raises(ValueError, match="period_end must be after period_start"):
            await service.get_metrics_for_period(
                dt.datetime(2024, 7, 31, tzinfo=dt.UTC),
                dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            )

    @pytest.mark.asyncio
    async def test_get_metrics_for_estate_filters_repositories(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Estate-scoped query includes only reports from matching estate."""
        estate_a_repo = await _create_repository(
            session_factory,
            owner="acme",
            name="alpha",
            estate_id="estate-a",
        )
        estate_b_repo = await _create_repository(
            session_factory,
            owner="acme",
            name="beta",
            estate_id="estate-b",
        )

        generated_at = dt.datetime(2024, 7, 15, tzinfo=dt.UTC)
        await _create_report(
            session_factory,
            ReportInsertSpec(
                repository_id=estate_a_repo,
                generated_at=generated_at,
                model_latency_ms=120,
                prompt_tokens=12,
                completion_tokens=4,
                total_tokens=16,
            ),
        )
        await _create_report(
            session_factory,
            ReportInsertSpec(
                repository_id=estate_b_repo,
                generated_at=generated_at,
                model_latency_ms=300,
                prompt_tokens=40,
                completion_tokens=8,
                total_tokens=48,
            ),
        )

        service = ReportingMetricsService(session_factory)
        period_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        period_end = dt.datetime(2024, 8, 1, tzinfo=dt.UTC)

        snapshot = await service.get_metrics_for_estate(
            "estate-a",
            period_start,
            period_end,
        )

        assert snapshot.total_reports == 1, (
            "Expected estate-scoped metrics to include only one matching report"
        )
        assert snapshot.reports_with_metrics == 1, (
            "Expected estate-scoped reports_with_metrics to match included report"
        )
        assert snapshot.avg_latency_ms == 120.0, (
            "Expected estate-scoped average latency to match included report"
        )
        assert snapshot.p95_latency_ms == 120.0, (
            "Expected estate-scoped p95 latency to match included report"
        )
        assert snapshot.total_prompt_tokens == 12, (
            "Expected estate-scoped prompt token sum to match included report"
        )
        assert snapshot.total_completion_tokens == 4, (
            "Expected estate-scoped completion token sum to match included report"
        )
        assert snapshot.total_tokens == 16, (
            "Expected estate-scoped total token sum to match included report"
        )
