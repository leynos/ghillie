"""Ingestion lag and health query services.

Provides on-demand computation of ingestion lag metrics per repository,
enabling operators to identify stalled or backlogged ingestion runs.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import typing as typ

from sqlalchemy import select

from ghillie.bronze import GithubIngestionOffset
from ghillie.common.time import utcnow

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclasses.dataclass(frozen=True, slots=True)
class IngestionHealthConfig:
    """Configuration for ingestion health thresholds."""

    stalled_threshold: dt.timedelta = dataclasses.field(
        default_factory=lambda: dt.timedelta(hours=1)
    )


@dataclasses.dataclass(frozen=True, slots=True)
class IngestionLagMetrics:
    """Computed lag metrics for a repository."""

    repo_slug: str
    time_since_last_ingestion_seconds: float | None
    oldest_watermark_age_seconds: float | None
    has_pending_cursors: bool
    is_stalled: bool


def _compute_lag_metrics(
    offset: GithubIngestionOffset,
    now: dt.datetime,
    stalled_threshold: dt.timedelta,
) -> IngestionLagMetrics:
    """Compute lag metrics from a GithubIngestionOffset row."""
    watermarks = [
        offset.last_commit_ingested_at,
        offset.last_pr_ingested_at,
        offset.last_issue_ingested_at,
        offset.last_doc_ingested_at,
    ]
    valid_watermarks = [w for w in watermarks if w is not None]

    if valid_watermarks:
        newest = max(valid_watermarks)
        oldest = min(valid_watermarks)
        time_since_last = (now - newest).total_seconds()
        oldest_age = (now - oldest).total_seconds()
    else:
        time_since_last = None
        oldest_age = None

    has_pending_cursors = any(
        [
            offset.last_commit_cursor is not None,
            offset.last_pr_cursor is not None,
            offset.last_issue_cursor is not None,
            offset.last_doc_cursor is not None,
        ]
    )

    # Determine if stalled: no watermarks, or newest watermark exceeds threshold
    if time_since_last is None:
        # No watermarks means never successfully ingested - consider stalled
        is_stalled = True
    else:
        is_stalled = time_since_last > stalled_threshold.total_seconds()

    return IngestionLagMetrics(
        repo_slug=offset.repo_external_id,
        time_since_last_ingestion_seconds=time_since_last,
        oldest_watermark_age_seconds=oldest_age,
        has_pending_cursors=has_pending_cursors,
        is_stalled=is_stalled,
    )


class IngestionHealthService:
    """Query ingestion lag and health status per repository.

    Computes lag metrics on-demand from GithubIngestionOffset watermarks.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        config: IngestionHealthConfig | None = None,
    ) -> None:
        """Create a health service bound to a database session factory."""
        self._session_factory = session_factory
        self._config = config or IngestionHealthConfig()

    async def get_lag_for_repository(
        self, repo_slug: str
    ) -> IngestionLagMetrics | None:
        """Compute lag metrics for a single repository.

        Returns None if the repository has no ingestion offset record.
        """
        async with self._session_factory() as session:
            offset = await session.scalar(
                select(GithubIngestionOffset).where(
                    GithubIngestionOffset.repo_external_id == repo_slug
                )
            )
            if offset is None:
                return None
            return _compute_lag_metrics(
                offset, utcnow(), self._config.stalled_threshold
            )

    async def get_all_repository_lags(self) -> list[IngestionLagMetrics]:
        """Compute lag metrics for all tracked repositories."""
        async with self._session_factory() as session:
            offsets = (await session.scalars(select(GithubIngestionOffset))).all()
            now = utcnow()
            return [
                _compute_lag_metrics(offset, now, self._config.stalled_threshold)
                for offset in offsets
            ]

    async def get_stalled_repositories(self) -> list[IngestionLagMetrics]:
        """Return repositories exceeding the stalled threshold.

        This includes repositories where the newest watermark is older than
        the configured threshold, or repositories with no watermarks (never
        successfully ingested).

        Note: Repositories with pending cursors (backlog) are tracked via
        the `has_pending_cursors` field but are not considered stalled unless
        they also exceed the time threshold.
        """
        all_lags = await self.get_all_repository_lags()
        return [lag for lag in all_lags if lag.is_stalled]
