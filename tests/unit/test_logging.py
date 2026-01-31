"""Unit tests for femtologging integration helpers."""

from __future__ import annotations

from ghillie.logging import format_log_message, log_exception, normalize_log_level


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
    assert level == "WARNING"
    assert invalid is False


def test_normalize_log_level_falls_back_on_invalid() -> None:
    """Invalid log levels fall back to INFO and flag invalid."""
    level, invalid = normalize_log_level("nope")
    assert level == "INFO"
    assert invalid is True


def test_format_log_message_uses_percent_formatting() -> None:
    """Percent formatting produces the expected message."""
    message = format_log_message("hello %s (%d)", "world", 3)
    assert message == "hello world (3)"


def test_log_exception_passes_exc_info() -> None:
    """log_exception forwards the exception payload to the logger."""
    logger = _FakeLogger()
    exc = ValueError("boom")

    log_exception(logger, "failed", exc)

    assert logger.calls == [("ERROR", "failed", exc, False)]
