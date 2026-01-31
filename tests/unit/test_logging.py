"""Unit tests for femtologging integration helpers."""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
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


def test_normalize_log_level_accepts_known_level() -> None:
    """Valid log levels are normalized without error."""
    level, invalid = normalize_log_level("warning")
    assert level == "WARNING", "Expected warning level to normalize to WARNING."
    assert invalid is False, "Expected known log level to be marked valid."


def test_normalize_log_level_with_none_defaults_to_info() -> None:
    """None log levels fall back to INFO and flag invalid."""
    level, invalid = normalize_log_level(None)
    assert level == "INFO", "Expected None log level to default to INFO."
    assert invalid is True, "Expected None log level to be marked invalid."


def test_normalize_log_level_with_empty_string_defaults_to_info() -> None:
    """Empty string log levels fall back to INFO and flag invalid."""
    level, invalid = normalize_log_level("")
    assert level == "INFO", "Expected empty log level to default to INFO."
    assert invalid is True, "Expected empty log level to be marked invalid."


def test_normalize_log_level_falls_back_on_invalid() -> None:
    """Invalid log levels fall back to INFO and flag invalid."""
    level, invalid = normalize_log_level("nope")
    assert level == "INFO", "Expected invalid log level to default to INFO."
    assert invalid is True, "Expected invalid log level to be marked invalid."


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


def test_log_error_forwards_stack_info() -> None:
    """log_error forwards stack_info to the logger."""
    logger = _FakeLogger()

    log_error(logger, "error: %s", "oops", stack_info=True)

    assert logger.calls == [("ERROR", "error: oops", None, True)], (
        "Expected ERROR log entry with stack_info."
    )


def test_log_exception_passes_exc_info() -> None:
    """log_exception forwards the exception payload to the logger."""
    logger = _FakeLogger()
    exc = ValueError("boom")

    log_exception(logger, "failed", exc)

    assert logger.calls == [("ERROR", "failed", exc, False)], (
        "Expected ERROR log entry with exc_info."
    )


def test_configure_logging_with_valid_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """configure_logging passes valid levels to basicConfig."""
    captured: dict[str, object] = {}

    def fake_basic_config(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("ghillie.logging.basicConfig", fake_basic_config)

    normalized, invalid = configure_logging("DEBUG")

    assert normalized == "DEBUG", "Expected DEBUG to remain normalized."
    assert invalid is False, "Expected valid level to be marked valid."
    assert captured.get("level") == "DEBUG", "Expected basicConfig level to match."


def test_configure_logging_with_invalid_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """configure_logging defaults invalid levels to INFO."""
    captured: dict[str, object] = {}

    def fake_basic_config(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("ghillie.logging.basicConfig", fake_basic_config)

    normalized, invalid = configure_logging("nope")

    assert normalized == "INFO", "Expected invalid level to normalize to INFO."
    assert invalid is True, "Expected invalid level to be marked invalid."
    assert captured.get("level") == "INFO", "Expected basicConfig to use INFO."
