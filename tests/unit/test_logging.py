"""Unit tests for femtologging integration helpers.

Run with:
    pytest tests/unit/test_logging.py
"""

import importlib

import pytest
from femtologging import get_logger

from ghillie.logging import (
    configure_logging,
    format_log_message,
    log_error,
    log_exception,
    log_info,
    log_warning,
    normalize_log_level,
)
from tests.helpers.femtologging_capture import capture_femto_logs


class _FakeLogger:
    """Collects log calls for assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object | None, bool]] = []

    def log(
        self,
        level: str,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> str:
        self.calls.append((level, message, exc_info, stack_info))
        return message


class TestNormalizeLogLevel:
    """Tests for normalize_log_level."""

    @pytest.mark.parametrize(
        ("input_level", "expected_level", "invalid_label"),
        [
            ("warning", "WARNING", "valid"),
            (None, "INFO", "invalid"),
            ("", "INFO", "invalid"),
            ("nope", "INFO", "invalid"),
        ],
    )
    def test_normalize_log_level(
        self,
        input_level: str | None,
        expected_level: str,
        invalid_label: str,
    ) -> None:
        """Normalize log levels and flag invalid inputs."""
        expected_invalid = invalid_label == "invalid"
        level, invalid = normalize_log_level(input_level)
        assert level == expected_level, (
            f"Expected {input_level!r} to normalize to {expected_level}."
        )
        assert invalid is expected_invalid, (
            f"Expected invalid flag to be {expected_invalid} for {input_level!r}."
        )


def test_format_log_message_uses_percent_formatting() -> None:
    """Percent formatting produces the expected message."""
    message = format_log_message("hello %s (%d)", "world", 3)
    assert message == "hello world (3)", "Expected percent formatting result."


def test_log_info_formats_and_passes_level() -> None:
    """log_info formats messages and emits INFO level."""
    logger = _FakeLogger()

    log_info(logger, "hello %s", "world")

    assert logger.calls == [("INFO", "hello world", None, False)], (
        "Expected INFO log entry with formatted message."
    )


def test_log_warning_forwards_exc_info() -> None:
    """log_warning forwards exc_info to the logger."""
    logger = _FakeLogger()
    exc = ValueError("boom")

    log_warning(logger, "warning: %s", "oops", exc_info=exc)

    assert logger.calls == [("WARNING", "warning: oops", exc, False)], (
        "Expected WARNING log entry with exc_info."
    )


def test_log_error_defaults_stack_info_false() -> None:
    """log_error defaults stack_info to False."""
    logger = _FakeLogger()

    log_error(logger, "error: %s", "oops")

    assert logger.calls == [("ERROR", "error: oops", None, False)], (
        "Expected ERROR log entry with stack_info disabled."
    )


def test_log_exception_passes_exc_info() -> None:
    """log_exception forwards the exception payload to the logger."""
    logger = _FakeLogger()
    exc = ValueError("boom")

    log_exception(logger, "failed", exc)

    assert logger.calls == [("ERROR", "failed", exc, False)], (
        "Expected ERROR log entry with exc_info."
    )


def test_femtologging_exposes_get_logger_alias() -> None:
    """The target femtologging snapshot exposes ``getLogger``."""
    femtologging = importlib.import_module("femtologging")

    assert hasattr(
        femtologging,
        "getLogger",
    ), (
        "test_femtologging_exposes_get_logger_alias expected "
        "femtologging.getLogger to exist alongside get_logger."
    )
    assert femtologging.getLogger("ghillie.test.alias") is get_logger(
        "ghillie.test.alias"
    ), (
        "test_femtologging_exposes_get_logger_alias expected getLogger to "
        "return the same logger singleton as get_logger."
    )


def test_femtologging_logger_exposes_is_enabled_for() -> None:
    """The target femtologging snapshot exposes ``isEnabledFor``."""
    logger = get_logger("ghillie.test.is-enabled")

    assert hasattr(
        logger,
        "isEnabledFor",
    ), (
        "test_femtologging_logger_exposes_is_enabled_for expected get_logger "
        "to return a logger with isEnabledFor."
    )
    is_enabled_for = logger.isEnabledFor
    assert callable(is_enabled_for), (
        "test_femtologging_logger_exposes_is_enabled_for expected "
        "logger.isEnabledFor to be callable."
    )
    assert is_enabled_for("INFO") is True, (
        "test_femtologging_logger_exposes_is_enabled_for expected "
        "logger.isEnabledFor('INFO') to report INFO as enabled."
    )


def test_femtologging_logger_exception_captures_exc_info() -> None:
    """The target femtologging snapshot exposes ``exception``."""
    logger = get_logger("ghillie.test.exception-method")

    with capture_femto_logs("ghillie.test.exception-method") as capture:
        error = ValueError("boom")
        logger.exception("failed via method", exc_info=error)
        capture.wait_for_count(1)

    assert len(capture.records) == 1, (
        "test_femtologging_logger_exception_captures_exc_info expected "
        "capture_femto_logs to record exactly one exception log."
    )
    record = capture.records[0]
    assert record.level == "ERROR", (
        "test_femtologging_logger_exception_captures_exc_info expected "
        "capture_femto_logs to preserve ERROR level."
    )
    assert record.message == "failed via method", (
        "test_femtologging_logger_exception_captures_exc_info expected "
        "capture_femto_logs to preserve the exception message."
    )
    assert record.exc_info is not None, (
        "test_femtologging_logger_exception_captures_exc_info expected "
        "capture_femto_logs to include exc_info from logger.exception."
    )


def test_femtologging_logger_warning_method_uses_warn_level() -> None:
    """The target femtologging snapshot exposes ``warning``."""
    logger = get_logger("ghillie.test.warning-method")

    with capture_femto_logs("ghillie.test.warning-method") as capture:
        logger.warning("careful now")
        capture.wait_for_count(1)

    assert len(capture.records) == 1, (
        "test_femtologging_logger_warning_method_uses_warn_level expected "
        "capture_femto_logs to record exactly one warning log."
    )
    record = capture.records[0]
    assert record.level == "WARN", (
        "test_femtologging_logger_warning_method_uses_warn_level expected "
        "capture_femto_logs to normalize warning() to WARN."
    )
    assert record.message == "careful now", (
        "test_femtologging_logger_warning_method_uses_warn_level expected "
        "capture_femto_logs to preserve the warning message."
    )


@pytest.mark.parametrize(
    ("input_level", "expected_normalized", "invalid_label"),
    [
        ("DEBUG", "DEBUG", "valid"),
        ("nope", "INFO", "invalid"),
    ],
)
def test_configure_logging(
    monkeypatch: pytest.MonkeyPatch,
    input_level: str,
    expected_normalized: str,
    invalid_label: str,
) -> None:
    """configure_logging normalizes input levels and flags invalid values."""
    captured: dict[str, object] = {}

    def fake_basic_config(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("ghillie.logging.basicConfig", fake_basic_config)

    normalized, invalid = configure_logging(input_level)
    expected_invalid = invalid_label == "invalid"

    assert normalized == expected_normalized, (
        f"Expected {input_level} to normalize to {expected_normalized}."
    )
    assert invalid is expected_invalid, (
        f"Expected invalid flag to be {expected_invalid} for {input_level}."
    )
    assert captured.get("level") == expected_normalized, (
        f"Expected basicConfig to use {expected_normalized}."
    )
    assert captured.get("force") is False, "Expected basicConfig to keep handlers."
