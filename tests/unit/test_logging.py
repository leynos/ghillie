"""Unit tests for femtologging integration helpers.

Run with:
    pytest tests/unit/test_logging.py
"""

from __future__ import annotations

import pytest

from ghillie.logging import (
    configure_logging,
    format_log_message,
    log_error,
    log_exception,
    log_info,
    log_warning,
    normalize_log_level,
)


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
