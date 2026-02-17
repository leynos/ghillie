"""Unit tests for report validation rules.

Tests the ``validate_repository_report`` function that checks generated
reports for basic correctness before persistence.
"""

from __future__ import annotations

import datetime as dt

import pytest

from ghillie.evidence.models import (
    CommitEvidence,
    ReportStatus,
    RepositoryEvidenceBundle,
    RepositoryMetadata,
)
from ghillie.reporting.validation import validate_repository_report
from ghillie.status.models import RepositoryStatusResult


def _make_bundle(*, commit_count: int = 3) -> RepositoryEvidenceBundle:
    """Build a minimal evidence bundle with *commit_count* commits."""
    commits = tuple(
        CommitEvidence(sha=f"sha-{i}", message=f"feat: change {i}")
        for i in range(commit_count)
    )
    return RepositoryEvidenceBundle(
        repository=RepositoryMetadata(
            id="repo-1",
            owner="acme",
            name="widget",
            default_branch="main",
        ),
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        commits=commits,
        event_fact_ids=tuple(range(commit_count)),
    )


def _make_result(
    *,
    summary: str = "acme/widget is on track with 3 events.",
    highlights: tuple[str, ...] = ("Delivered 2 feature PRs",),
    status: ReportStatus = ReportStatus.ON_TRACK,
) -> RepositoryStatusResult:
    """Build a minimal RepositoryStatusResult."""
    return RepositoryStatusResult(
        summary=summary,
        status=status,
        highlights=highlights,
    )


def _assert_validation_fails_with_code(
    summary: str,
    expected_code: str,
    scenario: str,
) -> None:
    """Assert that a summary triggers a specific validation failure code.

    Parameters
    ----------
    summary
        The summary string to validate.
    expected_code
        The issue code expected in the validation result.
    scenario
        Human-readable label for assertion messages.

    """
    bundle = _make_bundle()
    result = _make_result(summary=summary)
    outcome = validate_repository_report(bundle, result)

    assert not outcome.is_valid, (
        f"{scenario} summary should fail correctness validation"
    )
    codes = [issue.code for issue in outcome.issues]
    assert expected_code in codes, (
        f"{scenario} summary should emit {expected_code} issue code"
    )


class TestValidReportPassesChecks:
    """A well-formed result with plausible data should pass validation."""

    def test_valid_result_passes_basic_correctness_checks(self) -> None:
        """Verify a well-formed result passes all validation checks."""
        bundle = _make_bundle(commit_count=3)
        result = _make_result(highlights=("Did a thing",))
        outcome = validate_repository_report(bundle, result)

        assert outcome.is_valid, f"expected valid, got issues: {outcome.issues}"


class TestRejectsEmptySummary:
    """Reports with empty or whitespace-only summaries must be rejected."""

    @pytest.mark.parametrize(
        ("summary", "scenario"),
        [
            ("", "empty"),
            ("   \n  ", "whitespace-only"),
        ],
    )
    def test_rejects_empty_or_whitespace_only_summary(
        self,
        summary: str,
        scenario: str,
    ) -> None:
        """Reject empty and whitespace-only summaries."""
        _assert_validation_fails_with_code(summary, "empty_summary", scenario)


class TestRejectsObviouslyTruncatedSummary:
    """Summaries that look truncated should be rejected."""

    @pytest.mark.parametrize(
        ("summary", "scenario"),
        [
            ("The repository was active and...", "ascii-ellipsis"),
            ("The repository was active and\u2026", "unicode-ellipsis"),
        ],
    )
    def test_rejects_ellipsis_terminated_summary(
        self,
        summary: str,
        scenario: str,
    ) -> None:
        """Reject summaries ending in ASCII or Unicode ellipsis."""
        _assert_validation_fails_with_code(summary, "truncated_summary", scenario)


class TestRejectsImplausibleHighlightCount:
    """Highlight counts that are implausible relative to events."""

    def test_rejects_implausible_highlight_count_for_event_volume(self) -> None:
        """Many highlights from a bundle with very few events is suspicious."""
        bundle = _make_bundle(commit_count=1)
        # 20 highlights from 1 event is implausible
        highlights = tuple(f"Highlight {i}" for i in range(20))
        result = _make_result(highlights=highlights)
        outcome = validate_repository_report(bundle, result)

        assert not outcome.is_valid, (
            "Implausible highlight count should fail correctness validation"
        )
        codes = [issue.code for issue in outcome.issues]
        assert "implausible_highlights" in codes, (
            "Implausible highlight count should emit implausible_highlights code"
        )

    def test_accepts_proportional_highlights(self) -> None:
        """Highlights proportional to events should pass."""
        bundle = _make_bundle(commit_count=10)
        result = _make_result(highlights=("Did a thing", "Did another"))
        outcome = validate_repository_report(bundle, result)

        assert outcome.is_valid, (
            f"Proportional highlights should pass, got issues: {outcome.issues}"
        )


class TestValidationResultStructure:
    """ReportValidationResult exposes expected attributes."""

    def test_valid_result_has_no_issues(self) -> None:
        """Confirm a valid result has an empty issues tuple."""
        bundle = _make_bundle()
        result = _make_result(highlights=("One thing",))
        outcome = validate_repository_report(bundle, result)

        assert outcome.is_valid, (
            f"Expected valid outcome for non-empty summary, got: {outcome.issues}"
        )
        assert outcome.issues == (), "Valid outcome should contain zero issues"

    def test_invalid_result_contains_issues(self) -> None:
        """Confirm an invalid result carries at least one issue."""
        bundle = _make_bundle()
        result = _make_result(summary="")
        outcome = validate_repository_report(bundle, result)

        assert not outcome.is_valid, "Empty summary should produce an invalid outcome"
        assert len(outcome.issues) >= 1, (
            "Invalid outcome should contain at least one issue"
        )
        issue = outcome.issues[0]
        assert issue.code == "empty_summary", (
            "First issue should report empty_summary for empty summaries"
        )
        assert issue.message, "Issue message should be non-empty"
