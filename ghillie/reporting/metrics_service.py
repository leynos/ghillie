"""Query aggregate reporting metrics for operator cost and latency visibility.

This module computes Gold-layer reporting telemetry for a period, either across
all repositories or scoped to a single estate.

Usage
-----
Create a service and request a period snapshot:

>>> import datetime as dt
>>> from ghillie.reporting.metrics_service import ReportingMetricsService
>>> service = ReportingMetricsService(session_factory)
>>> snapshot = await service.get_metrics_for_period(
...     period_start=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
...     period_end=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
... )

"""

from __future__ import annotations

import dataclasses as dc
import math
import typing as typ

from sqlalchemy import select

from ghillie.gold.storage import Report, ReportScope
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    import datetime as dt

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


type MetricsRow = tuple[int | None, int | None, int | None, int | None]


@dc.dataclass(frozen=True, slots=True)
class ReportingMetricsSnapshot:
    """Aggregate reporting metrics for an operator-defined period.

    Attributes
    ----------
    period_start
        Start timestamp (inclusive) for the aggregation window.
    period_end
        End timestamp (exclusive) for the aggregation window.
    total_reports
        Number of reports generated in the selected period.
    reports_with_metrics
        Number of reports that contain at least one metrics field.
    avg_latency_ms
        Mean model latency in milliseconds, or ``None`` when unavailable.
    p95_latency_ms
        p95 model latency in milliseconds, or ``None`` when unavailable.
    total_prompt_tokens
        Sum of prompt tokens across reports in the period.
    total_completion_tokens
        Sum of completion tokens across reports in the period.
    total_tokens
        Sum of total token usage across reports in the period.

    """

    period_start: dt.datetime
    period_end: dt.datetime
    total_reports: int
    reports_with_metrics: int
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int


def _compute_p95(latencies_ms: list[int]) -> float | None:
    """Return the nearest-rank p95 latency from integer millisecond values."""
    if not latencies_ms:
        return None

    ordered = sorted(latencies_ms)
    index = max(math.ceil(0.95 * len(ordered)) - 1, 0)
    return float(ordered[index])


def _count_reports_with_metrics(rows: list[MetricsRow]) -> int:
    """Count rows with at least one non-null metrics field."""
    return sum(
        1
        for latency_ms, prompt_tokens, completion_tokens, total_tokens in rows
        if any(
            value is not None
            for value in (
                latency_ms,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            )
        )
    )


def _compute_latency_stats(rows: list[MetricsRow]) -> tuple[float | None, float | None]:
    """Compute average and p95 latency from non-null latency values."""
    latencies = [latency for latency, _p, _c, _t in rows if latency is not None]
    avg_latency_ms = (
        float(sum(latencies)) / float(len(latencies)) if latencies else None
    )
    p95_latency_ms = _compute_p95(latencies)
    return avg_latency_ms, p95_latency_ms


def _compute_token_totals(rows: list[MetricsRow]) -> tuple[int, int, int]:
    """Sum prompt, completion, and total tokens with nulls treated as zero."""
    total_prompt_tokens = sum(prompt_tokens or 0 for _l, prompt_tokens, _c, _t in rows)
    total_completion_tokens = sum(
        completion_tokens or 0 for _l, _p, completion_tokens, _t in rows
    )
    total_tokens = sum(
        total_tokens
        if total_tokens is not None
        else (prompt_tokens or 0) + (completion_tokens or 0)
        for _l, prompt_tokens, completion_tokens, total_tokens in rows
    )
    return total_prompt_tokens, total_completion_tokens, total_tokens


def _snapshot_from_rows(
    *,
    period_start: dt.datetime,
    period_end: dt.datetime,
    rows: list[MetricsRow],
) -> ReportingMetricsSnapshot:
    """Build a metrics snapshot from per-report metric rows."""
    total_reports = len(rows)
    reports_with_metrics = _count_reports_with_metrics(rows)
    avg_latency_ms, p95_latency_ms = _compute_latency_stats(rows)
    (
        total_prompt_tokens,
        total_completion_tokens,
        total_tokens,
    ) = _compute_token_totals(rows)

    return ReportingMetricsSnapshot(
        period_start=period_start,
        period_end=period_end,
        total_reports=total_reports,
        reports_with_metrics=reports_with_metrics,
        avg_latency_ms=avg_latency_ms,
        p95_latency_ms=p95_latency_ms,
        total_prompt_tokens=total_prompt_tokens,
        total_completion_tokens=total_completion_tokens,
        total_tokens=total_tokens,
    )


class ReportingMetricsService:
    """Query reporting cost and latency metrics from Gold-layer reports."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create service bound to an async session factory."""
        self._session_factory = session_factory

    def _validate_period(
        self,
        period_start: dt.datetime,
        period_end: dt.datetime,
    ) -> None:
        """Validate that period bounds are chronologically ordered."""
        if period_end <= period_start:
            msg = (
                "period_end must be after period_start, got "
                f"start={period_start.isoformat()}, end={period_end.isoformat()}"
            )
            raise ValueError(msg)

    async def _get_metrics(
        self,
        period_start: dt.datetime,
        period_end: dt.datetime,
        estate_id: str | None = None,
    ) -> ReportingMetricsSnapshot:
        """Return aggregate reporting metrics for a period.

        Optionally scope the aggregation to a single estate.
        """
        self._validate_period(period_start, period_end)
        rows = await self._fetch_rows(
            period_start=period_start,
            period_end=period_end,
            estate_id=estate_id,
        )
        return _snapshot_from_rows(
            period_start=period_start,
            period_end=period_end,
            rows=rows,
        )

    async def get_metrics_for_period(
        self,
        period_start: dt.datetime,
        period_end: dt.datetime,
    ) -> ReportingMetricsSnapshot:
        """Return aggregate reporting metrics for all repositories in a period.

        Parameters
        ----------
        period_start
            Start timestamp (inclusive) for the query window.
        period_end
            End timestamp (exclusive) for the query window.

        Returns
        -------
        ReportingMetricsSnapshot
            Aggregated report count, latency profile, and token totals.

        """
        return await self._get_metrics(
            period_start=period_start,
            period_end=period_end,
            estate_id=None,
        )

    async def get_metrics_for_estate(
        self,
        estate_id: str,
        period_start: dt.datetime,
        period_end: dt.datetime,
    ) -> ReportingMetricsSnapshot:
        """Return aggregate reporting metrics for one estate in a period.

        Parameters
        ----------
        estate_id
            Estate identifier used to scope repository reports.
        period_start
            Start timestamp (inclusive) for the query window.
        period_end
            End timestamp (exclusive) for the query window.

        Returns
        -------
        ReportingMetricsSnapshot
            Aggregated report count, latency profile, and token totals.

        """
        return await self._get_metrics(
            period_start=period_start,
            period_end=period_end,
            estate_id=estate_id,
        )

    async def _fetch_rows(
        self,
        *,
        period_start: dt.datetime,
        period_end: dt.datetime,
        estate_id: str | None,
    ) -> list[MetricsRow]:
        """Load per-report metrics rows for the selected scope and period."""
        stmt = select(
            Report.model_latency_ms,
            Report.prompt_tokens,
            Report.completion_tokens,
            Report.total_tokens,
        ).where(
            Report.scope == ReportScope.REPOSITORY,
            Report.generated_at >= period_start,
            Report.generated_at < period_end,
        )

        if estate_id is not None:
            stmt = stmt.join(
                Repository,
                Report.repository_id == Repository.id,
            ).where(Repository.estate_id == estate_id)

        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).tuples().all()
        return [typ.cast("MetricsRow", row) for row in rows]
