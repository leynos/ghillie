"""Emit structured observability events for reporting lifecycle execution.

This module defines event identifiers and a logger wrapper used by
``ReportingService`` to emit start, success, and failure telemetry.

Usage
-----
Create a logger and call lifecycle methods during report generation:

>>> event_logger = ReportingEventLogger()
>>> event_logger.log_report_started(
...     repo_slug="octo/reef",
...     window_start=start,
...     window_end=end,
... )

"""

from __future__ import annotations

import enum
import typing as typ

from ghillie.logging import get_logger, log_error, log_info

if typ.TYPE_CHECKING:
    import datetime as dt

    from ghillie.status.metrics import ModelInvocationMetrics

logger = get_logger(__name__)


class ReportingEventType(enum.StrEnum):
    """Structured log event types for reporting workflow runs."""

    REPORT_STARTED = "reporting.report.started"
    REPORT_COMPLETED = "reporting.report.completed"
    REPORT_FAILED = "reporting.report.failed"


class ReportingEventLogger:
    """Emit structured reporting events via femtologging."""

    def log_report_started(
        self,
        *,
        repo_slug: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> None:
        """Log report generation start for one repository window.

        Parameters
        ----------
        repo_slug
            Repository slug in ``owner/name`` format.
        window_start
            Start of the reporting window (inclusive).
        window_end
            End of the reporting window (exclusive).

        Returns
        -------
        None
            This method emits a structured log event and returns ``None``.

        """
        log_info(
            logger,
            "[%s] repo_slug=%s window_start=%s window_end=%s",
            ReportingEventType.REPORT_STARTED,
            repo_slug,
            window_start.isoformat(),
            window_end.isoformat(),
        )

    def log_report_completed(
        self,
        *,
        repo_slug: str,
        model: str,
        metrics: ModelInvocationMetrics | None,
    ) -> None:
        """Log successful report generation with latency and token fields.

        Parameters
        ----------
        repo_slug
            Repository slug in ``owner/name`` format.
        model
            Model identifier used for report generation.
        metrics
            Invocation metrics captured for the successful model call.

        Returns
        -------
        None
            This method emits a structured log event and returns ``None``.

        """
        latency = metrics.latency_ms if metrics is not None else None
        prompt_tokens = metrics.prompt_tokens if metrics is not None else None
        completion_tokens = metrics.completion_tokens if metrics is not None else None
        total_tokens = metrics.total_tokens if metrics is not None else None
        latency_text = "None" if latency is None else f"{latency:.3f}"
        log_info(
            logger,
            "[%s] repo_slug=%s model=%s latency_ms=%s "
            "prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            ReportingEventType.REPORT_COMPLETED,
            repo_slug,
            model,
            latency_text,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )

    def log_report_failed(
        self,
        *,
        repo_slug: str,
        error: BaseException,
        duration: dt.timedelta,
    ) -> None:
        """Log failed report generation with error details.

        Parameters
        ----------
        repo_slug
            Repository slug in ``owner/name`` format.
        error
            Raised exception from report generation.
        duration
            Elapsed runtime between report start and failure.

        Returns
        -------
        None
            This method emits a structured log event and returns ``None``.

        """
        log_error(
            logger,
            "[%s] repo_slug=%s duration_seconds=%.3f error_type=%s error_message=%s",
            ReportingEventType.REPORT_FAILED,
            repo_slug,
            duration.total_seconds(),
            type(error).__name__,
            str(error),
            exc_info=error,
        )
