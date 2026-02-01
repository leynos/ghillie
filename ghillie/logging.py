"""Logging helpers for femtologging integration.

This module centralizes log level normalization and formatting so Ghillie
emits structured, pre-formatted log messages consistently.

Example:
>>> from ghillie.logging import get_logger, log_info
>>> logger = get_logger(__name__)
>>> log_info(logger, "Started %s", "worker")

"""

from __future__ import annotations

import enum
import typing as typ

from femtologging import basicConfig, get_logger


class LogLevel(enum.StrEnum):
    """Supported log levels for femtologging."""

    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def normalize_log_level(level: str | None) -> tuple[str, bool]:
    """Normalize a log level string and report invalid inputs.

    Parameters
    ----------
    level : str | None
        Raw log level string to normalize.

    Returns
    -------
    tuple[str, bool]
        The normalized log level and a flag indicating invalid input.

    """
    if not level:
        return ("INFO", True)

    normalized = level.strip().upper()
    if normalized in LogLevel.__members__:
        return (normalized, False)

    return ("INFO", True)


def configure_logging(level: str, *, force: bool = False) -> tuple[str, bool]:
    """Configure femtologging and return the normalized level.

    Parameters
    ----------
    level : str
        Raw log level string to normalize.
    force : bool, optional
        Whether to replace any existing handler configuration.

    Returns
    -------
    tuple[str, bool]
        The normalized log level and a flag indicating invalid input.

    """
    normalized, invalid = normalize_log_level(level)
    basicConfig(level=normalized, force=force)
    return (normalized, invalid)


def _format_message(template: str, *args: object) -> str:
    """Format a message using percent-style interpolation."""
    return template % args


def format_log_message(template: str, *args: object) -> str:
    """Format a log message using percent-style interpolation.

    Parameters
    ----------
    template : str
        Message template using percent-style placeholders.
    *args : object
        Values to interpolate into the template.

    Returns
    -------
    str
        The formatted message.

    """
    return _format_message(template, *args)


class _SupportsLog(typ.Protocol):
    """Protocol for femtologging-compatible loggers."""

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
    """Log an INFO message with percent-style formatting.

    Parameters
    ----------
    logger : _SupportsLog
        Logger that receives the formatted message.
    template : str
        Message template using percent-style placeholders.
    *args : object
        Values to interpolate into the template.
    exc_info : object | None, optional
        Exception information to attach to the log record.

    Returns
    -------
    None
        No value is returned.

    """
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
    """Log a WARNING message with percent-style formatting.

    Parameters
    ----------
    logger : _SupportsLog
        Logger that receives the formatted message.
    template : str
        Message template using percent-style placeholders.
    *args : object
        Values to interpolate into the template.
    exc_info : object | None, optional
        Exception information to attach to the log record.

    Returns
    -------
    None
        No value is returned.

    """
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
    """Log an ERROR message with percent-style formatting.

    Parameters
    ----------
    logger : _SupportsLog
        Logger that receives the formatted message.
    template : str
        Message template using percent-style placeholders.
    *args : object
        Values to interpolate into the template.
    exc_info : object | None, optional
        Exception information to attach to the log record.

    Returns
    -------
    None
        No value is returned.

    """
    _log_at_level(
        logger,
        "ERROR",
        _format_message(template, *args),
        exc_info=exc_info,
    )


def log_exception(logger: _SupportsLog, message: str, exc: BaseException) -> None:
    """Log an exception with exc_info wired into femtologging.

    Parameters
    ----------
    logger : _SupportsLog
        Logger that receives the exception payload.
    message : str
        Pre-formatted message describing the failure.
    exc : BaseException
        Exception instance to attach as exc_info.

    Returns
    -------
    None
        No value is returned.

    """
    _log_at_level(logger, "ERROR", message, exc_info=exc)


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
