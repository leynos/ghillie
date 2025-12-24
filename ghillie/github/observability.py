"""Observability primitives for GitHub ingestion health.

Provides structured logging and error categorization for ingestion throughput,
failures, and backlog detection. All metrics are emitted as structured log
events suitable for parsing by log aggregators.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import typing as typ

from sqlalchemy.exc import (
    IntegrityError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)

from .errors import GitHubAPIError, GitHubConfigError, GitHubResponseShapeError

if typ.TYPE_CHECKING:
    import datetime as dt

    from .ingestion import GitHubIngestionResult

logger = logging.getLogger(__name__)

# HTTP status code threshold for server errors (5xx)
_HTTP_SERVER_ERROR_THRESHOLD = 500


class IngestionEventType(enum.StrEnum):
    """Structured log event types for ingestion observability."""

    RUN_STARTED = "ingestion.run.started"
    RUN_COMPLETED = "ingestion.run.completed"
    RUN_FAILED = "ingestion.run.failed"
    STREAM_COMPLETED = "ingestion.stream.completed"
    STREAM_TRUNCATED = "ingestion.stream.truncated"


class ErrorCategory(enum.StrEnum):
    """Categories for error classification in alerts."""

    TRANSIENT = "transient"
    CLIENT_ERROR = "client_error"
    SCHEMA_DRIFT = "schema_drift"
    CONFIGURATION = "configuration"
    DATABASE_CONNECTIVITY = "database_connectivity"
    DATA_INTEGRITY = "data_integrity"
    DATABASE_ERROR = "database_error"
    UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True, slots=True)
class IngestionRunContext:
    """Shared context for a single repository ingestion run."""

    repo_slug: str
    estate_id: str | None
    started_at: dt.datetime


_EXCEPTION_CATEGORY_MAP: tuple[tuple[type[BaseException], ErrorCategory], ...] = (
    (GitHubResponseShapeError, ErrorCategory.SCHEMA_DRIFT),
    (GitHubConfigError, ErrorCategory.CONFIGURATION),
    (OperationalError, ErrorCategory.DATABASE_CONNECTIVITY),
    (InterfaceError, ErrorCategory.DATABASE_CONNECTIVITY),
    (IntegrityError, ErrorCategory.DATA_INTEGRITY),
    (SQLAlchemyError, ErrorCategory.DATABASE_ERROR),
)


def categorize_error(exc: BaseException) -> ErrorCategory:
    """Categorize an exception for alerting purposes.

    Returns:
        ErrorCategory indicating the type of failure for alert routing.

    """
    # GitHubAPIError requires special handling for status code distinction
    if isinstance(exc, GitHubAPIError):
        if (
            exc.status_code is not None
            and exc.status_code >= _HTTP_SERVER_ERROR_THRESHOLD
        ):
            return ErrorCategory.TRANSIENT
        return ErrorCategory.CLIENT_ERROR

    # Use mapping for remaining exception types
    for exc_type, category in _EXCEPTION_CATEGORY_MAP:
        if isinstance(exc, exc_type):
            return category

    return ErrorCategory.UNKNOWN


class IngestionEventLogger:
    """Emit structured ingestion events via Python logging.

    All log events use lazy interpolation per project conventions. Events are
    emitted at INFO level for success, WARNING for truncation (backlog), and
    ERROR for failures.
    """

    def log_run_started(self, context: IngestionRunContext) -> None:
        """Log ingestion run start."""
        logger.info(
            "[%s] repo_slug=%s estate_id=%s started_at=%s",
            IngestionEventType.RUN_STARTED,
            context.repo_slug,
            context.estate_id,
            context.started_at.isoformat(),
        )

    def log_run_completed(
        self,
        context: IngestionRunContext,
        result: GitHubIngestionResult,
        duration: dt.timedelta,
    ) -> None:
        """Log successful ingestion run completion with metrics."""
        total_events = (
            result.commits_ingested
            + result.pull_requests_ingested
            + result.issues_ingested
            + result.doc_changes_ingested
        )
        logger.info(
            "[%s] repo_slug=%s estate_id=%s duration_seconds=%.3f "
            "commits_ingested=%d pull_requests_ingested=%d "
            "issues_ingested=%d doc_changes_ingested=%d total_events=%d",
            IngestionEventType.RUN_COMPLETED,
            context.repo_slug,
            context.estate_id,
            duration.total_seconds(),
            result.commits_ingested,
            result.pull_requests_ingested,
            result.issues_ingested,
            result.doc_changes_ingested,
            total_events,
        )

    def log_run_failed(
        self,
        context: IngestionRunContext,
        error: BaseException,
        duration: dt.timedelta,
    ) -> None:
        """Log failed ingestion run with error categorization."""
        category = categorize_error(error)
        logger.error(
            "[%s] repo_slug=%s estate_id=%s duration_seconds=%.3f "
            "error_type=%s error_category=%s error_message=%s",
            IngestionEventType.RUN_FAILED,
            context.repo_slug,
            context.estate_id,
            duration.total_seconds(),
            type(error).__name__,
            category,
            str(error),
            exc_info=error,
        )

    def log_stream_completed(
        self,
        context: IngestionRunContext,
        kind: str,
        events_ingested: int,
    ) -> None:
        """Log stream completion with ingested count."""
        logger.info(
            "[%s] repo_slug=%s stream_kind=%s events_ingested=%d",
            IngestionEventType.STREAM_COMPLETED,
            context.repo_slug,
            kind,
            events_ingested,
        )

    def log_stream_truncated(  # noqa: PLR0913
        self,
        context: IngestionRunContext,
        kind: str,
        events_processed: int,
        max_events: int,
        resume_cursor: str | None,
    ) -> None:
        """Log stream truncation (backlog warning)."""
        logger.warning(
            "[%s] repo_slug=%s stream_kind=%s events_processed=%d "
            "max_events=%d has_resume_cursor=%s",
            IngestionEventType.STREAM_TRUNCATED,
            context.repo_slug,
            kind,
            events_processed,
            max_events,
            resume_cursor is not None,
        )
