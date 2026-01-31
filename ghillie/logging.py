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


def format_log_message(template: str, *args: object) -> str:
    """Format a log message using percent-style interpolation."""
    return template % args


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


def log_exception(logger: _SupportsLog, message: str, exc: BaseException) -> None:
    """Log an exception with exc_info wired into femtologging."""
    logger.log("ERROR", message, exc_info=exc)


__all__ = [
    "configure_logging",
    "format_log_message",
    "get_logger",
    "log_exception",
    "normalize_log_level",
]
