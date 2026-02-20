"""Reporting service for generating repository status reports.

This module provides the ReportingService class which orchestrates the
reporting workflow: computing reporting windows, building evidence bundles,
invoking status models, and persisting reports with coverage records.

Usage
-----
Create a service and generate a report:

>>> from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
>>> from ghillie.evidence import EvidenceBundleService
>>> from ghillie.status import MockStatusModel
>>> from ghillie.reporting import (
...     ReportingConfig,
...     ReportingService,
...     ReportingServiceDependencies,
... )
>>>
>>> engine = create_async_engine("sqlite+aiosqlite:///ghillie.db")
>>> session_factory = async_sessionmaker(engine, expire_on_commit=False)
>>> dependencies = ReportingServiceDependencies(
...     session_factory=session_factory,
...     evidence_service=EvidenceBundleService(session_factory),
...     status_model=MockStatusModel(),
... )
>>> service = ReportingService(dependencies, config=ReportingConfig())
>>> report = await service.run_for_repository(repository_id, as_of=now)

"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import time
import typing as typ

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ghillie.common.time import utcnow
from ghillie.gold.storage import (
    Report,
    ReportCoverage,
    ReportReview,
    ReportScope,
    ReviewState,
    ValidationIssuePayload,
)
from ghillie.logging import get_logger, log_warning
from ghillie.reporting.errors import ReportValidationError
from ghillie.reporting.markdown import render_report_markdown
from ghillie.reporting.validation import (
    ReportValidationResult,
    validate_repository_report,
)
from ghillie.status.metrics import ModelInvocationMetrics
from ghillie.status.models import RepositoryStatusResult, to_machine_summary

from .config import ReportingConfig
from .sink import ReportMetadata

logger = get_logger(__name__)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.evidence.models import RepositoryEvidenceBundle
    from ghillie.evidence.service import EvidenceBundleService
    from ghillie.reporting.observability import ReportingEventLogger
    from ghillie.reporting.sink import ReportSink
    from ghillie.silver.storage import Repository
    from ghillie.status.protocol import StatusModel


@dc.dataclass(frozen=True, slots=True)
class ReportingServiceDependencies:
    """Core dependencies for ReportingService.

    Groups the mandatory collaborators into a single parameter object,
    reducing the constructor argument count and improving cohesion.

    Attributes
    ----------
    session_factory
        Async session factory for database access.
    evidence_service
        Service for building evidence bundles.
    status_model
        Model for generating status summaries.

    """

    session_factory: async_sessionmaker[AsyncSession]
    evidence_service: EvidenceBundleService
    status_model: StatusModel


@dc.dataclass(frozen=True, slots=True)
class ReportingWindow:
    """Time window for a repository report.

    Attributes
    ----------
    start
        Start of the window (inclusive).
    end
        End of the window (exclusive).

    """

    start: dt.datetime
    end: dt.datetime


class ReportingService:
    """Orchestrates repository status report generation.

    This service coordinates the full reporting workflow:

    1. Compute the next reporting window based on previous reports
    2. Build an evidence bundle from Silver layer data
    3. Invoke the status model to generate summaries
    4. Persist the report and coverage records to the Gold layer

    """

    def __init__(
        self,
        dependencies: ReportingServiceDependencies,
        config: ReportingConfig | None = None,
        report_sink: ReportSink | None = None,
        event_logger: ReportingEventLogger | None = None,
    ) -> None:
        """Configure the service with dependencies.

        Parameters
        ----------
        dependencies
            Core collaborators (session factory, evidence service, and
            status model) grouped into a single parameter object.
        config
            Optional reporting configuration; uses defaults if not provided.
        report_sink
            Optional sink for writing rendered Markdown reports. When
            provided, each generated report is rendered to Markdown and
            written via the sink. When ``None``, no Markdown output is
            produced.
        event_logger
            Optional structured event logger for reporting lifecycle events.

        """
        self._session_factory = dependencies.session_factory
        self._evidence_service = dependencies.evidence_service
        self._status_model = dependencies.status_model
        self._config = config or ReportingConfig()
        self._report_sink = report_sink
        self._event_logger = event_logger

    def _log_to_event_logger(
        self,
        event_method_name: str,
        **kwargs: typ.Any,  # noqa: ANN401
    ) -> None:
        """Delegate to an event logger method if the logger is configured.

        Parameters
        ----------
        event_method_name
            Name of the method to call on the event logger.
        **kwargs
            Arguments to pass to the event logger method.

        """
        if self._event_logger is None:
            return
        method = getattr(self._event_logger, event_method_name)
        method(**kwargs)

    async def compute_next_window(
        self,
        repository_id: str,
        as_of: dt.datetime | None = None,
    ) -> ReportingWindow:
        """Compute the next reporting window for a repository.

        The window starts where the previous report ended (if any), or
        `config.window_days` before `as_of` when no prior report exists.
        The window ends at `as_of`.

        Parameters
        ----------
        repository_id
            The Silver layer repository ID.
        as_of
            Reference time for window computation; defaults to now.

        Returns
        -------
        ReportingWindow
            Computed window with start and end timestamps.

        """
        window_end = as_of or utcnow()

        async with self._session_factory() as session:
            last_report = await self._fetch_last_report(session, repository_id)

        if last_report is not None:
            if last_report.window_end > window_end:
                msg = (
                    f"Cannot compute window for repository {repository_id}: "
                    f"as_of ({window_end.isoformat()}) predates the last report's "
                    f"window_end ({last_report.window_end.isoformat()})"
                )
                raise ValueError(msg)
            window_start = last_report.window_end
        else:
            window_start = window_end - dt.timedelta(days=self._config.window_days)

        return ReportingWindow(start=window_start, end=window_end)

    async def _fetch_last_report(
        self,
        session: AsyncSession,
        repository_id: str,
    ) -> Report | None:
        """Fetch the most recent repository report."""
        stmt = (
            select(Report)
            .where(
                Report.scope == ReportScope.REPOSITORY,
                Report.repository_id == repository_id,
            )
            .order_by(Report.window_end.desc())
            .limit(1)
        )
        return await session.scalar(stmt)

    def _validate_window(
        self,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> None:
        """Validate that the reporting window boundaries are well-ordered."""
        if window_end <= window_start:
            msg = (
                f"window_end must be after window_start, got "
                f"start={window_start.isoformat()}, end={window_end.isoformat()}"
            )
            raise ValueError(msg)

    async def _ensure_bundle(
        self,
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
        bundle: RepositoryEvidenceBundle | None,
    ) -> RepositoryEvidenceBundle:
        """Return a provided bundle or build one from the evidence service."""
        if bundle is not None:
            return bundle
        return await self._evidence_service.build_bundle(
            repository_id=repository_id,
            window_start=window_start,
            window_end=window_end,
        )

    async def generate_report(
        self,
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
        *,
        bundle: RepositoryEvidenceBundle | None = None,
    ) -> Report:
        """Generate a repository report for the given window.

        Builds an evidence bundle (unless provided), invokes the status model,
        validates the result, and persists the report with coverage records.
        If validation fails, the status model is retried up to
        ``config.validation_max_attempts`` times.  When all attempts fail, a
        ``ReportReview`` marker is created and ``ReportValidationError`` is
        raised.

        Parameters
        ----------
        repository_id
            The Silver layer repository ID.
        window_start
            Start of the reporting window (inclusive).
        window_end
            End of the reporting window (exclusive).
        bundle
            Optional pre-built evidence bundle. If not provided, one will be
            built from the evidence service.

        Returns
        -------
        Report
            The persisted report record.

        Raises
        ------
        ValueError
            If window_end is not after window_start.
        ReportValidationError
            If report validation fails after all retry attempts.

        """
        self._validate_window(window_start, window_end)
        bundle = await self._ensure_bundle(
            repository_id=repository_id,
            window_start=window_start,
            window_end=window_end,
            bundle=bundle,
        )
        repo_slug = self._get_repo_slug(bundle)
        started_at = time.monotonic()
        self._log_started(
            repo_slug=repo_slug, window_start=window_start, window_end=window_end
        )
        try:
            report, metrics = await self._generate_and_persist_report(
                repository_id=repository_id,
                window_start=window_start,
                window_end=window_end,
                bundle=bundle,
            )
        except Exception as exc:
            duration = dt.timedelta(seconds=time.monotonic() - started_at)
            self._log_failed(repo_slug=repo_slug, error=exc, duration=duration)
            raise
        self._log_completed(
            repo_slug=repo_slug, model=report.model or "unknown", metrics=metrics
        )
        return report

    async def _generate_and_persist_report(
        self,
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
        bundle: RepositoryEvidenceBundle,
    ) -> tuple[Report, ModelInvocationMetrics | None]:
        """Generate, validate, and persist a report for an evidence bundle."""
        status_result, validation, metrics = await self._invoke_with_retries(bundle)
        await self._handle_validation_result(
            validation=validation,
            repository_id=repository_id,
            window_start=window_start,
            window_end=window_end,
        )
        report = await self._persist_report(
            status_result=status_result,
            bundle=bundle,
            metrics=metrics,
        )
        return report, metrics

    def _log_started(
        self,
        repo_slug: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> None:
        """Log report generation start when observability logger is configured."""
        self._log_to_event_logger(
            "log_report_started",
            repo_slug=repo_slug,
            window_start=window_start,
            window_end=window_end,
        )

    def _log_failed(
        self,
        repo_slug: str,
        error: Exception,
        duration: dt.timedelta,
    ) -> None:
        """Log report generation failure when observability logger is configured."""
        self._log_to_event_logger(
            "log_report_failed",
            repo_slug=repo_slug,
            error=error,
            duration=duration,
        )

    def _log_completed(
        self,
        repo_slug: str,
        model: str,
        metrics: ModelInvocationMetrics | None,
    ) -> None:
        """Log report generation completion when observability logger is configured."""
        self._log_to_event_logger(
            "log_report_completed",
            repo_slug=repo_slug,
            model=model,
            metrics=metrics,
        )

    async def _handle_validation_result(
        self,
        validation: ReportValidationResult,
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> None:
        """Create review marker and raise when validation result is invalid."""
        if validation.is_valid:
            return

        review_id = await self._create_review_marker(
            repository_id=repository_id,
            window_start=window_start,
            window_end=window_end,
            validation=validation,
        )
        self._raise_validation_error(validation, review_id)

    def _raise_validation_error(
        self,
        validation: ReportValidationResult,
        review_id: str,
    ) -> typ.NoReturn:
        """Raise a structured validation error for exhausted retries."""
        raise ReportValidationError(
            issues=validation.issues,
            review_id=review_id,
        )

    async def _invoke_with_retries(
        self,
        bundle: RepositoryEvidenceBundle,
    ) -> tuple[
        RepositoryStatusResult,
        ReportValidationResult,
        ModelInvocationMetrics | None,
    ]:
        """Invoke the status model with validation retries.

        Returns the last status result and its validation outcome.
        """
        max_attempts = self._config.validation_max_attempts
        if max_attempts < 1:
            msg = f"validation_max_attempts must be >= 1, got {max_attempts}"
            raise ValueError(msg)

        status_result: RepositoryStatusResult | None = None
        validation: ReportValidationResult | None = None
        invocation_metrics: ModelInvocationMetrics | None = None

        for _attempt in range(max_attempts):
            started_at = time.monotonic()
            status_result = await self._status_model.summarize_repository(bundle)
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            invocation_metrics = self._merge_invocation_metrics(elapsed_ms)
            validation = validate_repository_report(bundle, status_result)
            if validation.is_valid:
                break

        if status_result is None or validation is None:
            msg = (
                "Status model did not run; this indicates an invalid retry "
                f"configuration (max_attempts={max_attempts})."
            )
            raise RuntimeError(msg)

        return status_result, validation, invocation_metrics

    def _merge_invocation_metrics(
        self, latency_ms: float
    ) -> ModelInvocationMetrics | None:
        """Merge adapter metrics with measured service-level latency."""
        if not hasattr(self._status_model, "last_invocation_metrics"):
            return None

        raw_metrics = getattr(self._status_model, "last_invocation_metrics", None)
        if isinstance(raw_metrics, ModelInvocationMetrics):
            return dc.replace(raw_metrics, latency_ms=latency_ms)

        return ModelInvocationMetrics(latency_ms=latency_ms)

    async def _create_review_marker(
        self,
        *,
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
        validation: ReportValidationResult,
    ) -> str:
        """Persist a ``ReportReview`` row and return its ID."""
        model = self._get_model_identifier()
        attempt_count = self._config.validation_max_attempts
        validation_issues: list[ValidationIssuePayload] = [
            {"code": issue.code, "message": issue.message}
            for issue in validation.issues
        ]
        review = ReportReview(
            repository_id=repository_id,
            window_start=window_start,
            window_end=window_end,
            model=model,
            attempt_count=attempt_count,
            validation_issues=validation_issues,
            state=ReviewState.PENDING,
        )

        async with self._session_factory() as session:
            session.add(review)
            try:
                await session.flush()
                await session.commit()
            except IntegrityError:
                await session.rollback()
            else:
                review_id: str = review.id
                return review_id

            # A marker already exists for this repository/window. Update it so
            # repeated failed runs are idempotent and keep the latest details.
            existing = await session.scalar(
                select(ReportReview).where(
                    ReportReview.repository_id == repository_id,
                    ReportReview.window_start == window_start,
                    ReportReview.window_end == window_end,
                )
            )
            if existing is None:
                msg = (
                    "Failed to upsert ReportReview marker for repository "
                    f"{repository_id} in window {window_start.isoformat()} - "
                    f"{window_end.isoformat()}."
                )
                raise RuntimeError(msg)

            existing.model = model
            existing.attempt_count = attempt_count
            existing.validation_issues = validation_issues
            existing.state = ReviewState.PENDING
            await session.flush()
            existing_id = existing.id
            await session.commit()
            return existing_id

    async def _persist_report(
        self,
        *,
        status_result: RepositoryStatusResult,
        bundle: RepositoryEvidenceBundle,
        metrics: ModelInvocationMetrics | None,
    ) -> Report:
        """Persist the validated report and write to sink."""
        repository_id = bundle.repository.id
        machine_summary = to_machine_summary(status_result)
        model_latency_ms = self._to_latency_milliseconds(metrics)

        async with self._session_factory() as session, session.begin():
            report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=repository_id,
                window_start=bundle.window_start,
                window_end=bundle.window_end,
                model=self._get_model_identifier(),
                human_text=status_result.summary,
                machine_summary=machine_summary,
                model_latency_ms=model_latency_ms,
                prompt_tokens=metrics.prompt_tokens if metrics is not None else None,
                completion_tokens=(
                    metrics.completion_tokens if metrics is not None else None
                ),
                total_tokens=metrics.total_tokens if metrics is not None else None,
            )
            session.add(report)
            await session.flush()
            self._create_coverage_records(session, report, bundle)
            report_id = report.id

        async with self._session_factory() as session:
            persisted = await session.get(Report, report_id)
            if persisted is None:  # pragma: no cover - defensive check
                msg = f"Report {report_id} not found after commit"
                raise RuntimeError(msg)

        if self._report_sink is not None:
            await self._write_to_sink(persisted, repository_id)

        return persisted

    def _to_latency_milliseconds(
        self, metrics: ModelInvocationMetrics | None
    ) -> int | None:
        """Convert measured floating-point latency to integer milliseconds."""
        if metrics is None or metrics.latency_ms is None:
            return None
        return round(metrics.latency_ms)

    def _get_model_identifier(self) -> str:
        """Return the model identifier for report metadata."""
        # Check for model_id attribute on the status model
        model_id = getattr(self._status_model, "model_id", None)
        if model_id is not None:
            return str(model_id)
        # Fall back to class-based identification
        model_class = type(self._status_model).__name__
        if model_class == "MockStatusModel":
            return "mock-v1"
        return model_class.lower()

    def _create_coverage_records(
        self,
        session: AsyncSession,
        report: Report,
        bundle: RepositoryEvidenceBundle,
    ) -> None:
        """Create ReportCoverage records linking events to the report."""
        for event_fact_id in bundle.event_fact_ids:
            coverage = ReportCoverage(
                report_id=report.id,
                event_fact_id=event_fact_id,
            )
            session.add(coverage)

    async def _write_to_sink(
        self,
        report: Report,
        repository_id: str,
    ) -> None:
        """Render a report to Markdown and write it via the sink.

        Parameters
        ----------
        report
            The persisted Gold layer report.
        repository_id
            The Silver layer repository ID, used to fetch owner/name.

        """
        from ghillie.silver.storage import Repository as _Repository

        async with self._session_factory() as session:
            repo: Repository | None = await session.get(_Repository, repository_id)

        if repo is None:
            log_warning(
                logger,
                "Skipping sink write for report %s: repository %s not found",
                report.id,
                repository_id,
            )
            return

        markdown = render_report_markdown(
            report, owner=repo.github_owner, name=repo.github_name
        )

        # Caller guarantees _report_sink is not None; guard defensively.
        if self._report_sink is None:  # pragma: no cover
            return

        metadata: ReportMetadata = ReportMetadata(
            owner=repo.github_owner,
            name=repo.github_name,
            report_id=str(report.id),
            window_end=report.window_end.strftime("%Y-%m-%d"),
        )
        await self._report_sink.write_report(markdown, metadata=metadata)

    def _get_repo_slug(self, bundle: RepositoryEvidenceBundle) -> str:
        """Return owner/name slug for reporting logs."""
        return bundle.repository.slug

    async def run_for_repository(
        self,
        repository_id: str,
        as_of: dt.datetime | None = None,
    ) -> Report | None:
        """Run the full reporting workflow for a repository.

        Computes the next window and generates a report. Returns None if
        there are no events in the window worth reporting.

        Parameters
        ----------
        repository_id
            The Silver layer repository ID.
        as_of
            Reference time for window computation; defaults to now.

        Returns
        -------
        Report | None
            The generated report, or None if no events exist in the window.

        """
        window = await self.compute_next_window(repository_id, as_of=as_of)

        # Build bundle to check if there are events
        bundle = await self._evidence_service.build_bundle(
            repository_id=repository_id,
            window_start=window.start,
            window_end=window.end,
        )

        if bundle.total_event_count == 0:
            return None

        # Pass the pre-built bundle to avoid rebuilding it
        return await self.generate_report(
            repository_id=repository_id,
            window_start=window.start,
            window_end=window.end,
            bundle=bundle,
        )
