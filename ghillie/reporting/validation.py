"""Validation rules for generated repository reports.

Checks that a ``RepositoryStatusResult`` produced by a status model
meets basic correctness heuristics before the report is persisted to
the Gold layer.  Validation is deliberately conservative — it catches
obviously broken output without trying to assess narrative quality.

Public API
----------
ReportValidationIssue
    Frozen dataclass describing a single validation failure.
ReportValidationResult
    Frozen dataclass aggregating zero or more issues.
validate_repository_report
    Pure function that applies all checks and returns a result.
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    from ghillie.evidence.models import RepositoryEvidenceBundle
    from ghillie.status.models import RepositoryStatusResult

# Highlights exceeding this multiple of the event count are implausible.
_HIGHLIGHT_EVENT_RATIO = 5


@dc.dataclass(frozen=True, slots=True)
class ReportValidationIssue:
    """A single validation failure.

    Attributes
    ----------
    code
        Machine-readable identifier (e.g. ``"empty_summary"``).
    message
        Human-readable explanation of the problem.

    """

    code: str
    message: str


@dc.dataclass(frozen=True, slots=True)
class ReportValidationResult:
    """Outcome of validating a status model result.

    Attributes
    ----------
    issues
        Tuple of detected problems.  Empty when the result is valid.

    """

    issues: tuple[ReportValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        """Return ``True`` when no issues were detected."""
        return len(self.issues) == 0


def _check_empty_summary(
    result: RepositoryStatusResult,
) -> ReportValidationIssue | None:
    if not result.summary or not result.summary.strip():
        return ReportValidationIssue(
            code="empty_summary",
            message="Summary is empty or contains only whitespace.",
        )
    return None


def _check_truncated_summary(
    result: RepositoryStatusResult,
) -> ReportValidationIssue | None:
    summary = result.summary.rstrip()
    if summary.endswith(("...", "\u2026")):
        return ReportValidationIssue(
            code="truncated_summary",
            message="Summary appears truncated (trailing ellipsis).",
        )
    return None


def _check_implausible_highlights(
    bundle: RepositoryEvidenceBundle,
    result: RepositoryStatusResult,
) -> ReportValidationIssue | None:
    event_count = max(bundle.total_event_count, 1)
    highlight_count = len(result.highlights)
    if highlight_count > event_count * _HIGHLIGHT_EVENT_RATIO:
        return ReportValidationIssue(
            code="implausible_highlights",
            message=(
                f"Highlight count ({highlight_count}) is implausibly high "
                f"relative to event count ({bundle.total_event_count})."
            ),
        )
    return None


def validate_repository_report(
    bundle: RepositoryEvidenceBundle,
    result: RepositoryStatusResult,
) -> ReportValidationResult:
    """Validate a status model result against the source evidence bundle.

    Parameters
    ----------
    bundle
        The evidence bundle that was passed to the status model.
    result
        The status model's output.

    Returns
    -------
    ReportValidationResult
        Aggregated validation outcome.

    """
    checks: list[ReportValidationIssue] = []

    empty = _check_empty_summary(result)
    if empty is not None:
        checks.append(empty)

    truncated = _check_truncated_summary(result)
    if truncated is not None:
        checks.append(truncated)

    implausible = _check_implausible_highlights(bundle, result)
    if implausible is not None:
        checks.append(implausible)

    return ReportValidationResult(issues=tuple(checks))
