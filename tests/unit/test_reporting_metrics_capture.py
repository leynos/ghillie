"""Unit tests for reporting metrics capture in ``ReportingService``."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ
from unittest import mock

import pytest

from ghillie.evidence import EvidenceBundleService
from ghillie.evidence.models import (
    CommitEvidence,
    ReportStatus,
    RepositoryEvidenceBundle,
    RepositoryMetadata,
)
from ghillie.reporting import ReportingConfig
from ghillie.reporting.service import ReportingService, ReportingServiceDependencies
from ghillie.status import MockStatusModel
from ghillie.status.metrics import ModelInvocationMetrics
from ghillie.status.models import RepositoryStatusResult
from tests.unit.conftest import create_test_repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.gold.storage import Report
    from ghillie.status.protocol import StatusModel


def _valid_result(summary: str = "acme/widget is on track") -> RepositoryStatusResult:
    return RepositoryStatusResult(
        summary=summary,
        status=ReportStatus.ON_TRACK,
        highlights=("Delivered feature work",),
    )


def _invalid_result() -> RepositoryStatusResult:
    return RepositoryStatusResult(
        summary="",
        status=ReportStatus.ON_TRACK,
    )


def _make_bundle(repo_id: str) -> RepositoryEvidenceBundle:
    return RepositoryEvidenceBundle(
        repository=RepositoryMetadata(
            id=repo_id,
            owner="acme",
            name="widget",
            default_branch="main",
        ),
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        commits=(CommitEvidence(sha="abc123", message="feat: add metrics"),),
        event_fact_ids=(),
    )


class _StaticMetricsStatusModel:
    """Status model that emits fixed token metrics."""

    def __init__(
        self,
        *,
        metrics: ModelInvocationMetrics,
        delay_s: float = 0.0,
    ) -> None:
        self._metrics = metrics
        self._delay_s = delay_s
        self.last_invocation_metrics: ModelInvocationMetrics | None = None

    async def summarize_repository(
        self,
        evidence: RepositoryEvidenceBundle,
    ) -> RepositoryStatusResult:
        del evidence
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        self.last_invocation_metrics = self._metrics
        return _valid_result()


class _NoMetricsStatusModel:
    """Status model that does not expose invocation metrics."""

    async def summarize_repository(
        self,
        evidence: RepositoryEvidenceBundle,
    ) -> RepositoryStatusResult:
        del evidence
        return _valid_result()


class _RetryingMetricsStatusModel:
    """Status model that fails validation once, then succeeds."""

    def __init__(self) -> None:
        self._attempt = 0
        self.last_invocation_metrics: ModelInvocationMetrics | None = None

    async def summarize_repository(
        self,
        evidence: RepositoryEvidenceBundle,
    ) -> RepositoryStatusResult:
        del evidence
        self._attempt += 1
        if self._attempt == 1:
            self.last_invocation_metrics = ModelInvocationMetrics(
                prompt_tokens=11,
                completion_tokens=1,
                total_tokens=12,
            )
            return _invalid_result()

        self.last_invocation_metrics = ModelInvocationMetrics(
            prompt_tokens=22,
            completion_tokens=8,
            total_tokens=30,
        )
        return _valid_result(summary="retry succeeded")


def _build_service(
    session_factory: async_sessionmaker[AsyncSession],
    status_model: object,
    *,
    max_attempts: int = 2,
    event_logger: mock.MagicMock | None = None,
) -> ReportingService:
    """Build ``ReportingService`` with controllable status model and logger."""
    evidence_service = mock.MagicMock(spec=EvidenceBundleService)
    deps = ReportingServiceDependencies(
        session_factory=session_factory,
        evidence_service=evidence_service,
        status_model=typ.cast("StatusModel", status_model),
    )
    config = ReportingConfig(validation_max_attempts=max_attempts)
    return ReportingService(deps, config=config, event_logger=event_logger)


class TestReportingMetricsCapture:
    """Tests for persisting latency and token metrics on reports."""

    async def _generate_test_report(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        status_model: object,
    ) -> Report:
        """Generate a report using the given status model (test helper)."""
        repo_id = await create_test_repository(session_factory)
        bundle = _make_bundle(repo_id)
        service = _build_service(session_factory, status_model)

        return await service.generate_report(
            repository_id=repo_id,
            window_start=bundle.window_start,
            window_end=bundle.window_end,
            bundle=bundle,
        )

    @pytest.mark.asyncio
    async def test_persists_latency_and_tokens_from_status_model(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Generated reports include latency and token usage metrics."""
        repo_id = await create_test_repository(session_factory)
        bundle = _make_bundle(repo_id)

        status_model = _StaticMetricsStatusModel(
            metrics=ModelInvocationMetrics(
                prompt_tokens=120,
                completion_tokens=30,
                total_tokens=150,
            ),
            delay_s=0.01,
        )
        service = _build_service(session_factory, status_model)

        report = await service.generate_report(
            repository_id=repo_id,
            window_start=bundle.window_start,
            window_end=bundle.window_end,
            bundle=bundle,
        )

        assert report.model_latency_ms is not None
        assert report.model_latency_ms >= 1
        assert report.prompt_tokens == 120
        assert report.completion_tokens == 30
        assert report.total_tokens == 150

    @pytest.mark.asyncio
    async def test_mock_model_reports_zero_token_usage(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """``MockStatusModel`` should persist zero-token usage per run."""
        report = await self._generate_test_report(session_factory, MockStatusModel())

        assert report.prompt_tokens == 0
        assert report.completion_tokens == 0
        assert report.total_tokens == 0

    @pytest.mark.asyncio
    async def test_missing_metrics_attribute_persists_null_columns(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Models without metrics side-channel keep report metrics nullable."""
        report = await self._generate_test_report(
            session_factory,
            _NoMetricsStatusModel(),
        )

        assert report.model_latency_ms is None
        assert report.prompt_tokens is None
        assert report.completion_tokens is None
        assert report.total_tokens is None

    @pytest.mark.asyncio
    async def test_retry_persists_metrics_from_last_successful_attempt(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When retry succeeds, persisted metrics come from successful attempt."""
        report = await self._generate_test_report(
            session_factory,
            _RetryingMetricsStatusModel(),
        )

        assert report.human_text == "retry succeeded"
        assert report.prompt_tokens == 22
        assert report.completion_tokens == 8
        assert report.total_tokens == 30


class TestReportingEventLoggerIntegration:
    """Tests for reporting lifecycle logging integration."""

    @pytest.mark.asyncio
    async def test_success_calls_started_and_completed(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Successful runs should emit start and completion events."""
        repo_id = await create_test_repository(session_factory)
        bundle = _make_bundle(repo_id)
        event_logger = mock.MagicMock()

        service = _build_service(
            session_factory,
            _StaticMetricsStatusModel(metrics=ModelInvocationMetrics(total_tokens=1)),
            event_logger=event_logger,
        )

        await service.generate_report(
            repository_id=repo_id,
            window_start=bundle.window_start,
            window_end=bundle.window_end,
            bundle=bundle,
        )

        event_logger.log_report_started.assert_called_once()
        event_logger.log_report_completed.assert_called_once()
        event_logger.log_report_failed.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_calls_failed_event(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Exceptions should emit a failed event before re-raising."""
        repo_id = await create_test_repository(session_factory)
        bundle = _make_bundle(repo_id)
        event_logger = mock.MagicMock()

        status_model = mock.MagicMock()
        status_model.summarize_repository = mock.AsyncMock(
            side_effect=RuntimeError("status backend unavailable")
        )

        service = _build_service(
            session_factory,
            status_model,
            event_logger=event_logger,
        )

        with pytest.raises(RuntimeError, match="status backend unavailable"):
            await service.generate_report(
                repository_id=repo_id,
                window_start=bundle.window_start,
                window_end=bundle.window_end,
                bundle=bundle,
            )

        event_logger.log_report_started.assert_called_once()
        event_logger.log_report_failed.assert_called_once()
