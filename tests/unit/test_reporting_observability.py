"""Unit tests for reporting observability logging."""

from __future__ import annotations

import datetime as dt

import pytest

from ghillie.reporting.observability import ReportingEventLogger, ReportingEventType
from ghillie.status.metrics import ModelInvocationMetrics
from tests.helpers.femtologging_capture import capture_femto_logs


class TestReportingEventLogger:
    """Tests for ``ReportingEventLogger`` structured log events."""

    @pytest.fixture
    def logger_instance(self) -> ReportingEventLogger:
        """Return a fresh reporting event logger."""
        return ReportingEventLogger()

    def test_log_report_started_emits_info(
        self,
        logger_instance: ReportingEventLogger,
    ) -> None:
        """Start events should be logged at INFO with repo context."""
        with capture_femto_logs("ghillie.reporting.observability") as capture:
            logger_instance.log_report_started(
                repo_slug="acme/widget",
                window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            )
            capture.wait_for_count(1)
            record = capture.records[0]
            assert record.level == "INFO"
            assert ReportingEventType.REPORT_STARTED in record.message
            assert "acme/widget" in record.message

    def test_log_report_completed_emits_metrics(
        self,
        logger_instance: ReportingEventLogger,
    ) -> None:
        """Completion events include latency and token usage fields."""
        with capture_femto_logs("ghillie.reporting.observability") as capture:
            logger_instance.log_report_completed(
                repo_slug="acme/widget",
                model="gpt-5.1-thinking",
                metrics=ModelInvocationMetrics(
                    latency_ms=123.4,
                    prompt_tokens=200,
                    completion_tokens=80,
                    total_tokens=280,
                ),
            )
            capture.wait_for_count(1)
            record = capture.records[0]
            assert record.level == "INFO"
            assert ReportingEventType.REPORT_COMPLETED in record.message
            assert "latency_ms=123.400" in record.message
            assert "prompt_tokens=200" in record.message
            assert "completion_tokens=80" in record.message
            assert "total_tokens=280" in record.message

    def test_log_report_failed_emits_error(
        self,
        logger_instance: ReportingEventLogger,
    ) -> None:
        """Failure events should be logged at ERROR with error metadata."""
        error = RuntimeError("boom")

        with capture_femto_logs("ghillie.reporting.observability") as capture:
            logger_instance.log_report_failed(
                repo_slug="acme/widget",
                error=error,
                duration=dt.timedelta(seconds=2),
            )
            capture.wait_for_count(1)
            record = capture.records[0]
            assert record.level == "ERROR"
            assert ReportingEventType.REPORT_FAILED in record.message
            assert "error_type=RuntimeError" in record.message
            assert "boom" in record.message
            assert record.exc_info is not None
