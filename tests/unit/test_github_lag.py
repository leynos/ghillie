"""Unit tests for the GitHub ingestion lag health service."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest

from ghillie.bronze import GithubIngestionOffset
from ghillie.github.lag import (
    IngestionHealthConfig,
    IngestionHealthService,
    IngestionLagMetrics,
    _compute_lag_metrics,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TestComputeLagMetrics:
    """Tests for the _compute_lag_metrics helper function."""

    @staticmethod
    def _create_offset_and_compute(
        offset_kwargs: dict[str, str | dt.datetime | None],
        now: dt.datetime | None = None,
        threshold: dt.timedelta | None = None,
    ) -> IngestionLagMetrics:
        """Create offset and compute lag metrics with sensible defaults."""
        if now is None:
            now = dt.datetime(2025, 1, 15, 12, 0, 0, tzinfo=dt.UTC)
        if threshold is None:
            threshold = dt.timedelta(hours=1)
        # Merge defaults without mutating input dict
        merged_kwargs = {"repo_external_id": "octo/reef", **offset_kwargs}
        offset = GithubIngestionOffset(**merged_kwargs)
        return _compute_lag_metrics(offset, now, threshold)

    def test_all_watermarks_present(self) -> None:
        """Correctly computes lag when all watermarks are set."""
        now = dt.datetime(2025, 1, 15, 12, 0, 0, tzinfo=dt.UTC)
        offset = GithubIngestionOffset(
            repo_external_id="octo/reef",
            last_commit_ingested_at=now - dt.timedelta(hours=1),
            last_pr_ingested_at=now - dt.timedelta(hours=2),
            last_issue_ingested_at=now - dt.timedelta(hours=3),
            last_doc_ingested_at=now - dt.timedelta(hours=4),
        )
        threshold = dt.timedelta(hours=1)

        result = _compute_lag_metrics(offset, now, threshold)

        assert result.repo_slug == "octo/reef"
        # Newest is commit at 1 hour ago
        assert result.time_since_last_ingestion_seconds == 3600.0
        # Oldest is doc at 4 hours ago
        assert result.oldest_watermark_age_seconds == 14400.0
        assert result.has_pending_cursors is False
        # 1 hour equals threshold, not exceeding
        assert result.is_stalled is False

    def test_stalled_when_exceeds_threshold(self) -> None:
        """Repository is stalled when newest watermark exceeds threshold."""
        now = dt.datetime(2025, 1, 15, 12, 0, 0, tzinfo=dt.UTC)
        offset = GithubIngestionOffset(
            repo_external_id="octo/reef",
            last_commit_ingested_at=now - dt.timedelta(hours=2),
        )
        threshold = dt.timedelta(hours=1)

        result = _compute_lag_metrics(offset, now, threshold)

        assert result.is_stalled is True
        assert result.time_since_last_ingestion_seconds == 7200.0

    def test_no_watermarks_is_stalled(self) -> None:
        """Repository with no watermarks is considered stalled."""
        now = dt.datetime(2025, 1, 15, 12, 0, 0, tzinfo=dt.UTC)
        offset = GithubIngestionOffset(repo_external_id="octo/reef")
        threshold = dt.timedelta(hours=1)

        result = _compute_lag_metrics(offset, now, threshold)

        assert result.is_stalled is True
        assert result.time_since_last_ingestion_seconds is None
        assert result.oldest_watermark_age_seconds is None

    def test_pending_cursors_detected(self) -> None:
        """Pending cursors are correctly detected."""
        now = dt.datetime(2025, 1, 15, 12, 0, 0, tzinfo=dt.UTC)
        result = self._create_offset_and_compute(
            {
                "last_commit_ingested_at": now - dt.timedelta(minutes=30),
                "last_commit_cursor": "Y3Vyc29yOjEyMzQ1",
            },
            now=now,
        )

        assert result.has_pending_cursors is True
        assert result.is_stalled is False

    def test_multiple_pending_cursors(self) -> None:
        """Multiple pending cursors are detected."""
        result = self._create_offset_and_compute(
            {
                "last_commit_cursor": "cursor1",
                "last_pr_cursor": "cursor2",
            },
        )

        assert result.has_pending_cursors is True

    def test_partial_watermarks(self) -> None:
        """Computes lag correctly with partial watermarks."""
        now = dt.datetime(2025, 1, 15, 12, 0, 0, tzinfo=dt.UTC)
        offset = GithubIngestionOffset(
            repo_external_id="octo/reef",
            last_commit_ingested_at=now - dt.timedelta(minutes=10),
            last_pr_ingested_at=now - dt.timedelta(minutes=30),
            # issue and doc watermarks are None
        )
        threshold = dt.timedelta(hours=1)

        result = _compute_lag_metrics(offset, now, threshold)

        assert result.time_since_last_ingestion_seconds == 600.0  # 10 minutes
        assert result.oldest_watermark_age_seconds == 1800.0  # 30 minutes
        assert result.is_stalled is False


class TestIngestionHealthService:
    """Tests for the IngestionHealthService."""

    @staticmethod
    async def _add_offsets(
        session_factory: async_sessionmaker[AsyncSession],
        *offsets: GithubIngestionOffset,
    ) -> None:
        """Add multiple offset records to the database."""
        async with session_factory() as session, session.begin():
            for offset in offsets:
                session.add(offset)

    @pytest.fixture
    def service(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> IngestionHealthService:
        """Return a health service with default config."""
        return IngestionHealthService(session_factory)

    @pytest.fixture
    def service_short_threshold(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> IngestionHealthService:
        """Return a health service with 5 minute threshold."""
        config = IngestionHealthConfig(stalled_threshold=dt.timedelta(minutes=5))
        return IngestionHealthService(session_factory, config=config)

    @pytest.mark.asyncio
    async def test_get_lag_for_unknown_repository(
        self, service: IngestionHealthService
    ) -> None:
        """Returns None for repositories without offset records."""
        result = await service.get_lag_for_repository("unknown/repo")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_lag_for_known_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        service: IngestionHealthService,
    ) -> None:
        """Returns lag metrics for repositories with offset records."""
        now = dt.datetime.now(dt.UTC)
        await self._add_offsets(
            session_factory,
            GithubIngestionOffset(
                repo_external_id="octo/reef",
                last_commit_ingested_at=now - dt.timedelta(minutes=30),
            ),
        )

        result = await service.get_lag_for_repository("octo/reef")

        assert result is not None
        assert result.repo_slug == "octo/reef"
        assert result.time_since_last_ingestion_seconds is not None
        # 30 minutes = 1800 seconds, but allow some tolerance for test execution
        lag_s = result.time_since_last_ingestion_seconds
        assert 1799 <= lag_s <= 1810, (
            f"Expected ~1800s (30 min), got {lag_s}s; "
            "tolerance accounts for test execution time"
        )
        assert result.is_stalled is False  # default threshold is 1 hour

    @pytest.mark.asyncio
    async def test_get_all_repository_lags_empty(
        self, service: IngestionHealthService
    ) -> None:
        """Returns empty list when no repositories are tracked."""
        result = await service.get_all_repository_lags()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_all_repository_lags_multiple(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        service: IngestionHealthService,
    ) -> None:
        """Returns lag metrics for all tracked repositories."""
        now = dt.datetime.now(dt.UTC)
        await self._add_offsets(
            session_factory,
            GithubIngestionOffset(
                repo_external_id="octo/reef",
                last_commit_ingested_at=now - dt.timedelta(minutes=10),
            ),
            GithubIngestionOffset(
                repo_external_id="octo/coral",
                last_commit_ingested_at=now - dt.timedelta(minutes=20),
            ),
        )

        result = await service.get_all_repository_lags()

        assert len(result) == 2
        slugs = {r.repo_slug for r in result}
        assert slugs == {"octo/reef", "octo/coral"}

    @pytest.mark.asyncio
    async def test_get_stalled_repositories_none_stalled(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        service: IngestionHealthService,
    ) -> None:
        """Returns empty list when no repositories are stalled."""
        now = dt.datetime.now(dt.UTC)
        await self._add_offsets(
            session_factory,
            GithubIngestionOffset(
                repo_external_id="octo/reef",
                last_commit_ingested_at=now - dt.timedelta(minutes=30),
            ),
        )

        result = await service.get_stalled_repositories()

        assert result == []

    @pytest.mark.asyncio
    async def test_get_stalled_repositories_with_stalled(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        service_short_threshold: IngestionHealthService,
    ) -> None:
        """Returns stalled repositories exceeding threshold."""
        now = dt.datetime.now(dt.UTC)
        await self._add_offsets(
            session_factory,
            # Recent ingestion - not stalled
            GithubIngestionOffset(
                repo_external_id="octo/reef",
                last_commit_ingested_at=now - dt.timedelta(minutes=2),
            ),
            # Old ingestion - stalled (exceeds 5 minute threshold)
            GithubIngestionOffset(
                repo_external_id="octo/coral",
                last_commit_ingested_at=now - dt.timedelta(minutes=10),
            ),
        )

        result = await service_short_threshold.get_stalled_repositories()

        assert len(result) == 1
        assert result[0].repo_slug == "octo/coral"
        assert result[0].is_stalled is True

    @pytest.mark.asyncio
    async def test_get_stalled_includes_no_watermarks(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        service: IngestionHealthService,
    ) -> None:
        """Repositories with no watermarks are considered stalled."""
        await self._add_offsets(
            session_factory,
            GithubIngestionOffset(repo_external_id="octo/reef"),
        )

        result = await service.get_stalled_repositories()

        assert len(result) == 1
        assert result[0].repo_slug == "octo/reef"
        assert result[0].is_stalled is True
        assert result[0].time_since_last_ingestion_seconds is None


class TestIngestionHealthConfig:
    """Tests for the IngestionHealthConfig dataclass."""

    def test_default_threshold(self) -> None:
        """Default stalled threshold is 1 hour."""
        config = IngestionHealthConfig()
        assert config.stalled_threshold == dt.timedelta(hours=1)

    def test_custom_threshold(self) -> None:
        """Custom stalled threshold can be set."""
        config = IngestionHealthConfig(stalled_threshold=dt.timedelta(minutes=30))
        assert config.stalled_threshold == dt.timedelta(minutes=30)


class TestIngestionLagMetrics:
    """Tests for the IngestionLagMetrics dataclass."""

    def test_frozen(self) -> None:
        """Lag metrics are immutable."""
        metrics = IngestionLagMetrics(
            repo_slug="octo/reef",
            time_since_last_ingestion_seconds=100.0,
            oldest_watermark_age_seconds=200.0,
            has_pending_cursors=False,
            is_stalled=False,
        )
        with pytest.raises(AttributeError):
            metrics.repo_slug = "other/repo"  # type: ignore[misc]

    def test_all_fields(self) -> None:
        """All fields are accessible."""
        metrics = IngestionLagMetrics(
            repo_slug="octo/reef",
            time_since_last_ingestion_seconds=100.0,
            oldest_watermark_age_seconds=200.0,
            has_pending_cursors=True,
            is_stalled=True,
        )
        assert metrics.repo_slug == "octo/reef"
        assert metrics.time_since_last_ingestion_seconds == 100.0
        assert metrics.oldest_watermark_age_seconds == 200.0
        assert metrics.has_pending_cursors is True
        assert metrics.is_stalled is True
