"""Unit tests for the GitHub ingestion observability module."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError

from ghillie.github.errors import (
    GitHubAPIError,
    GitHubConfigError,
    GitHubResponseShapeError,
)
from ghillie.github.ingestion import GitHubIngestionResult
from ghillie.github.observability import (
    ErrorCategory,
    IngestionEventLogger,
    IngestionEventType,
    IngestionRunContext,
    StreamTruncationDetails,
    categorize_error,
)
from tests.helpers.femtologging_capture import capture_femto_logs


class TestCategorizeError:
    """Tests for error categorization."""

    def test_github_api_error_5xx_is_transient(self) -> None:
        """GitHub 5xx errors are classified as transient."""
        exc = GitHubAPIError.http_error(502)
        assert categorize_error(exc) == ErrorCategory.TRANSIENT

    def test_github_api_error_503_is_transient(self) -> None:
        """GitHub 503 errors are classified as transient."""
        exc = GitHubAPIError.http_error(503)
        assert categorize_error(exc) == ErrorCategory.TRANSIENT

    def test_github_api_error_4xx_is_client_error(self) -> None:
        """GitHub 4xx errors are classified as client errors."""
        exc = GitHubAPIError.http_error(401)
        assert categorize_error(exc) == ErrorCategory.CLIENT_ERROR

    def test_github_api_error_graphql_is_client_error(self) -> None:
        """GitHub GraphQL errors without status code are client errors."""
        exc = GitHubAPIError.graphql_errors([{"message": "Bad request"}])
        assert categorize_error(exc) == ErrorCategory.CLIENT_ERROR

    def test_github_response_shape_error_is_schema_drift(self) -> None:
        """Missing response fields indicate schema drift."""
        exc = GitHubResponseShapeError.missing("repository")
        assert categorize_error(exc) == ErrorCategory.SCHEMA_DRIFT

    def test_github_config_error_is_configuration(self) -> None:
        """Configuration errors are classified accordingly."""
        exc = GitHubConfigError.missing_token()
        assert categorize_error(exc) == ErrorCategory.CONFIGURATION

    def test_operational_error_is_database_connectivity(self) -> None:
        """SQLAlchemy OperationalError is database connectivity."""
        exc = OperationalError("connection failed", None, Exception("test"))
        assert categorize_error(exc) == ErrorCategory.DATABASE_CONNECTIVITY

    def test_interface_error_is_database_connectivity(self) -> None:
        """SQLAlchemy InterfaceError is database connectivity."""
        exc = InterfaceError("interface failed", None, Exception("test"))
        assert categorize_error(exc) == ErrorCategory.DATABASE_CONNECTIVITY

    def test_integrity_error_is_data_integrity(self) -> None:
        """SQLAlchemy IntegrityError is data integrity."""
        exc = IntegrityError("duplicate key", None, Exception("test"))
        assert categorize_error(exc) == ErrorCategory.DATA_INTEGRITY

    def test_unknown_exception_is_unknown(self) -> None:
        """Unknown exception types default to unknown category."""
        exc = ValueError("something went wrong")
        assert categorize_error(exc) == ErrorCategory.UNKNOWN

    def test_runtime_error_is_unknown(self) -> None:
        """Generic RuntimeError defaults to unknown category."""
        exc = RuntimeError("unexpected")
        assert categorize_error(exc) == ErrorCategory.UNKNOWN


class TestIngestionEventLogger:
    """Tests for the IngestionEventLogger structured logging."""

    @pytest.fixture
    def logger_instance(self) -> IngestionEventLogger:
        """Return a fresh event logger instance."""
        return IngestionEventLogger()

    @pytest.fixture
    def context(self) -> IngestionRunContext:
        """Return a sample ingestion run context."""
        return IngestionRunContext(
            repo_slug="octo/reef",
            estate_id="wildside",
            started_at=dt.datetime(2025, 1, 15, 12, 0, 0, tzinfo=dt.UTC),
        )

    def test_log_run_started_emits_info(
        self,
        logger_instance: IngestionEventLogger,
        context: IngestionRunContext,
    ) -> None:
        """Run started events are logged at INFO level."""
        with capture_femto_logs("ghillie.github.observability") as capture:
            logger_instance.log_run_started(context)

        capture.wait_for_count(1)
        assert len(capture.records) == 1
        record = capture.records[0]
        assert record.level == "INFO"
        assert IngestionEventType.RUN_STARTED in record.message
        assert "octo/reef" in record.message
        assert "wildside" in record.message

    def test_log_run_completed_includes_metrics(
        self,
        logger_instance: IngestionEventLogger,
        context: IngestionRunContext,
    ) -> None:
        """Run completed events include all ingestion metrics."""
        result = GitHubIngestionResult(
            repo_slug="octo/reef",
            commits_ingested=12,
            pull_requests_ingested=3,
            issues_ingested=5,
            doc_changes_ingested=2,
        )
        duration = dt.timedelta(seconds=45.2)

        with capture_femto_logs("ghillie.github.observability") as capture:
            logger_instance.log_run_completed(context, result, duration)

        capture.wait_for_count(1)
        assert len(capture.records) == 1
        record = capture.records[0]
        assert record.level == "INFO"
        assert IngestionEventType.RUN_COMPLETED in record.message
        assert "commits_ingested=12" in record.message
        assert "pull_requests_ingested=3" in record.message
        assert "issues_ingested=5" in record.message
        assert "doc_changes_ingested=2" in record.message
        assert "total_events=22" in record.message
        assert "duration_seconds=45.200" in record.message

    def test_log_run_failed_includes_error_details(
        self,
        logger_instance: IngestionEventLogger,
        context: IngestionRunContext,
    ) -> None:
        """Run failed events include error type and category."""
        error = GitHubAPIError.http_error(502)
        duration = dt.timedelta(seconds=12.5)

        with capture_femto_logs("ghillie.github.observability") as capture:
            logger_instance.log_run_failed(context, error, duration)

        capture.wait_for_count(1)
        assert len(capture.records) == 1
        record = capture.records[0]
        assert record.level == "ERROR"
        assert IngestionEventType.RUN_FAILED in record.message
        assert "error_type=GitHubAPIError" in record.message
        assert "error_category=transient" in record.message
        assert "GitHub GraphQL HTTP 502" in record.message
        assert record.exc_info is not None

    def test_log_stream_completed_emits_info(
        self,
        logger_instance: IngestionEventLogger,
        context: IngestionRunContext,
    ) -> None:
        """Stream completed events are logged at INFO level."""
        with capture_femto_logs("ghillie.github.observability") as capture:
            logger_instance.log_stream_completed(context, "commit", 12)

        capture.wait_for_count(1)
        assert len(capture.records) == 1
        record = capture.records[0]
        assert record.level == "INFO"
        assert IngestionEventType.STREAM_COMPLETED in record.message
        assert "stream_kind=commit" in record.message
        assert "events_ingested=12" in record.message

    def test_log_stream_truncated_emits_warning(
        self,
        logger_instance: IngestionEventLogger,
        context: IngestionRunContext,
    ) -> None:
        """Stream truncated events are logged at WARN level."""
        details = StreamTruncationDetails(
            kind="commit",
            events_processed=500,
            max_events=500,
            resume_cursor="Y3Vyc29yOjEyMzQ1",
        )
        with capture_femto_logs("ghillie.github.observability") as capture:
            logger_instance.log_stream_truncated(context, details)

        capture.wait_for_count(1)
        assert len(capture.records) == 1
        record = capture.records[0]
        assert record.level == "WARN"
        assert IngestionEventType.STREAM_TRUNCATED in record.message
        assert "stream_kind=commit" in record.message
        assert "events_processed=500" in record.message
        assert "max_events=500" in record.message
        assert "has_resume_cursor=True" in record.message

    def test_log_stream_truncated_no_cursor(
        self,
        logger_instance: IngestionEventLogger,
        context: IngestionRunContext,
    ) -> None:
        """Stream truncated events correctly report missing cursor."""
        details = StreamTruncationDetails(
            kind="pull_request",
            events_processed=500,
            max_events=500,
            resume_cursor=None,
        )
        with capture_femto_logs("ghillie.github.observability") as capture:
            logger_instance.log_stream_truncated(context, details)

        capture.wait_for_count(1)
        assert len(capture.records) == 1
        record = capture.records[0]
        assert "has_resume_cursor=False" in record.message


class TestIngestionEventType:
    """Tests for the IngestionEventType enum."""

    def test_event_type_values(self) -> None:
        """Event type values follow the expected naming convention."""
        assert IngestionEventType.RUN_STARTED == "ingestion.run.started"
        assert IngestionEventType.RUN_COMPLETED == "ingestion.run.completed"
        assert IngestionEventType.RUN_FAILED == "ingestion.run.failed"
        assert IngestionEventType.STREAM_COMPLETED == "ingestion.stream.completed"
        assert IngestionEventType.STREAM_TRUNCATED == "ingestion.stream.truncated"


class TestIngestionRunContext:
    """Tests for the IngestionRunContext dataclass."""

    def test_context_is_frozen(self) -> None:
        """Context is immutable after creation."""
        context = IngestionRunContext(
            repo_slug="octo/reef",
            estate_id="wildside",
            started_at=dt.datetime.now(dt.UTC),
        )
        with pytest.raises(AttributeError):
            context.repo_slug = "other/repo"  # type: ignore[misc]

    def test_context_with_none_estate_id(self) -> None:
        """Context accepts None estate_id."""
        context = IngestionRunContext(
            repo_slug="octo/reef",
            estate_id=None,
            started_at=dt.datetime.now(dt.UTC),
        )
        assert context.estate_id is None
