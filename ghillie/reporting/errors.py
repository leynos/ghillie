"""Errors specific to the reporting module."""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    from ghillie.reporting.validation import ReportValidationIssue


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


class ReportValidationError(ReportingError):
    """Raised when a generated report fails validation after all retries.

    Carries the validation issues and the ID of the human-review marker
    so that callers (including the API layer) can surface actionable
    detail to operators.

    Parameters
    ----------
    issues
        Validation issues detected in the last attempt.
    review_id
        Identifier of the ``ReportReview`` row created for operator
        follow-up.

    """

    issues: tuple[ReportValidationIssue, ...]
    review_id: str

    def __init__(
        self,
        *,
        issues: tuple[ReportValidationIssue, ...],
        review_id: str,
    ) -> None:
        """Initialize with validation issues and review identifier."""
        self.issues = issues
        self.review_id = review_id
        count = len(issues)
        msg = (
            f"Report failed validation with {count} issue(s) "
            f"after retries exhausted (review_id={review_id})"
        )
        super().__init__(msg)
