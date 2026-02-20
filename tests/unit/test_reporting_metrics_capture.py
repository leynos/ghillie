"""Unit tests for reporting metrics capture in ``ReportingService``.

This module verifies that report-generation runs persist latency/token metrics
and emit lifecycle observability events with the expected payloads.

Usage
-----
Run this module directly while iterating on reporting metrics behaviour:

>>> # uv run pytest tests/unit/test_reporting_metrics_capture.py -v

"""

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
    """Return a valid status result for reporting tests."""
    return RepositoryStatusResult(
        summary=summary,
        status=ReportStatus.ON_TRACK,
        highlights=("Delivered feature work",),
    )


def _invalid_result() -> RepositoryStatusResult:
    """Return an invalid status result that fails report validation."""
    return RepositoryStatusResult(
        summary="",
        status=ReportStatus.ON_TRACK,
    )


def _make_bundle(repo_id: str) -> RepositoryEvidenceBundle:
    """Build a deterministic evidence bundle for report-generation tests."""
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

        assert report.model_latency_ms is not None, (
            "Expected persisted report to include measured model latency"
        )
        assert report.model_latency_ms >= 1, (
            "Expected measured model latency to be at least 1 ms"
        )
        assert report.prompt_tokens == 120, (
            "Expected persisted prompt token usage to match model metrics"
        )
        assert report.completion_tokens == 30, (
            "Expected persisted completion token usage to match model metrics"
        )
        assert report.total_tokens == 150, (
            "Expected persisted total token usage to match model metrics"
        )

    @pytest.mark.asyncio
    async def test_mock_model_reports_zero_token_usage(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """``MockStatusModel`` should persist zero-token usage per run."""
        report = await self._generate_test_report(session_factory, MockStatusModel())

        assert report.prompt_tokens == 0, (
            "Expected mock model prompt token usage to persist as zero"
        )
        assert report.completion_tokens == 0, (
            "Expected mock model completion token usage to persist as zero"
        )
        assert report.total_tokens == 0, (
            "Expected mock model total token usage to persist as zero"
        )

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

        assert report.model_latency_ms is None, (
            "Expected latency column to remain null without metrics side-channel"
        )
        assert report.prompt_tokens is None, (
            "Expected prompt token column to remain null without metrics side-channel"
        )
        assert report.completion_tokens is None, (
            "Expected completion token column to remain null without "
            "metrics side-channel"
        )
        assert report.total_tokens is None, (
            "Expected total token column to remain null without metrics side-channel"
        )

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

        assert report.human_text == "retry succeeded", (
            "Expected successful retry summary to be persisted"
        )
        assert report.prompt_tokens == 22, (
            "Expected prompt token usage from successful retry attempt"
        )
        assert report.completion_tokens == 8, (
            "Expected completion token usage from successful retry attempt"
        )
        assert report.total_tokens == 30, (
            "Expected total token usage from successful retry attempt"
        )


class TestReportingEventLoggerIntegration:
    """Tests for reporting lifecycle logging integration."""

    @pytest.mark.asyncio
    async def test_success_calls_started_and_completed(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Successful runs should emit start and completion events with payloads."""
        repo_id = await create_test_repository(session_factory)
        bundle = _make_bundle(repo_id)
        event_logger = mock.MagicMock()

        service = _build_service(
            session_factory,
            _StaticMetricsStatusModel(metrics=ModelInvocationMetrics(total_tokens=1)),
            event_logger=event_logger,
        )

        report = await service.generate_report(
            repository_id=repo_id,
            window_start=bundle.window_start,
            window_end=bundle.window_end,
            bundle=bundle,
        )

        event_logger.log_report_started.assert_called_once()
        started_kwargs = event_logger.log_report_started.call_args.kwargs
        assert started_kwargs["repo_slug"] == bundle.repository.slug, (
            "Expected started event repo_slug to match the repository bundle slug"
        )
        assert started_kwargs["window_start"] == bundle.window_start, (
            "Expected started event window_start to match reporting window"
        )
        assert started_kwargs["window_end"] == bundle.window_end, (
            "Expected started event window_end to match reporting window"
        )

        event_logger.log_report_completed.assert_called_once()
        completed_kwargs = event_logger.log_report_completed.call_args.kwargs
        assert completed_kwargs["repo_slug"] == bundle.repository.slug, (
            "Expected completed event repo_slug to match the repository bundle slug"
        )
        assert completed_kwargs["model"] == (report.model or "unknown"), (
            "Expected completed event model to match persisted report model"
        )
        metrics = completed_kwargs["metrics"]
        assert isinstance(metrics, ModelInvocationMetrics), (
            "Expected completed event metrics payload to use ModelInvocationMetrics"
        )
        assert report.model_latency_ms == round(metrics.latency_ms or 0.0), (
            "Expected persisted latency to match rounded completed-event latency"
        )
        assert report.prompt_tokens == metrics.prompt_tokens, (
            "Expected persisted prompt tokens to match completed-event metrics"
        )
        assert report.completion_tokens == metrics.completion_tokens, (
            "Expected persisted completion tokens to match completed-event metrics"
        )
        assert report.total_tokens == metrics.total_tokens, (
            "Expected persisted total tokens to match completed-event metrics"
        )

        event_logger.log_report_failed.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_calls_failed_event(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Exceptions should emit start and failure events with payload context."""
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
        failed_kwargs = event_logger.log_report_failed.call_args.kwargs
        assert failed_kwargs["repo_slug"] == bundle.repository.slug, (
            "Expected failed event repo_slug to match the repository bundle slug"
        )
        assert isinstance(failed_kwargs["error"], RuntimeError), (
            "Expected failed event error payload to preserve RuntimeError type"
        )
        assert str(failed_kwargs["error"]) == "status backend unavailable", (
            "Expected failed event error message to match raised runtime error"
        )
        assert failed_kwargs["duration"] > dt.timedelta(0), (
            "Expected failed event duration to be positive"
        )
        event_logger.log_report_completed.assert_not_called()
