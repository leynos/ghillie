"""Errors specific to the reporting module."""

from __future__ import annotations


class ReportingError(Exception):
    """Base class for reporting module errors."""


class EstateReportError(ReportingError):
    """Raised when report generation fails for one or more repositories in an estate.

    This exception wraps multiple underlying exceptions that occurred during
    concurrent report generation, preserving diagnostic information for each
    failure.

    Parameters
    ----------
    exceptions
        Sequence of exceptions that occurred during estate-wide report generation.

    Attributes
    ----------
    exceptions
        Immutable tuple of the underlying exceptions that caused the failures.

    """

    exceptions: tuple[Exception, ...]

    def __init__(self, exceptions: list[Exception]) -> None:
        """Initialize with the list of exceptions that occurred during generation."""
        self.exceptions = tuple(exceptions)
        count = len(self.exceptions)
        message = f"Estate report generation failed: {count} error(s) occurred"
        super().__init__(message)
