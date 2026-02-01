"""Logging helpers built around femtologging."""

from __future__ import annotations

import typing as typ

from femtologging import basicConfig, get_logger

_LOG_LEVELS = {
    "TRACE",
    "DEBUG",
    "INFO",
    "WARN",
    "WARNING",
    "ERROR",
    "CRITICAL",
}


def normalize_log_level(level: str | None) -> tuple[str, bool]:
    """Normalize a log level string and report invalid inputs."""
    if not level:
        return ("INFO", True)

    normalized = level.strip().upper()
    if normalized in _LOG_LEVELS:
        return (normalized, False)

    return ("INFO", True)


def configure_logging(level: str, *, force: bool = True) -> tuple[str, bool]:
    """Configure femtologging and return the normalized level."""
    normalized, invalid = normalize_log_level(level)
    basicConfig(level=normalized, force=force)
    return (normalized, invalid)


def _format_message(template: str, *args: object) -> str:
    return template % args


def format_log_message(template: str, *args: object) -> str:
    """Format a log message using percent-style interpolation."""
    return _format_message(template, *args)


class _SupportsLog(typ.Protocol):
    def log(
        self,
        level: str,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> str | None: ...


def _log_at_level(
    logger: _SupportsLog,
    level: str,
    message: str,
    *,
    exc_info: object | None = None,
) -> None:
    """Log a pre-formatted message at the specified level."""
    logger.log(
        level,
        message,
        exc_info=exc_info,
        stack_info=False,
    )


def log_info(
    logger: _SupportsLog,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Log an INFO message with percent-style formatting."""
    _log_at_level(
        logger,
        "INFO",
        _format_message(template, *args),
        exc_info=exc_info,
    )


def log_warning(
    logger: _SupportsLog,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Log a WARNING message with percent-style formatting."""
    _log_at_level(
        logger,
        "WARNING",
        _format_message(template, *args),
        exc_info=exc_info,
    )


def log_error(
    logger: _SupportsLog,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Log an ERROR message with percent-style formatting."""
    _log_at_level(
        logger,
        "ERROR",
        _format_message(template, *args),
        exc_info=exc_info,
    )


def log_exception(logger: _SupportsLog, message: str, exc: BaseException) -> None:
    """Log an exception with exc_info wired into femtologging."""
    logger.log("ERROR", message, exc_info=exc)


__all__ = [
    "configure_logging",
    "format_log_message",
    "get_logger",
    "log_error",
    "log_exception",
    "log_info",
    "log_warning",
    "normalize_log_level",
]
