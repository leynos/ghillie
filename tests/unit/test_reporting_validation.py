"""Unit tests for report validation rules.

Tests the ``validate_repository_report`` function that checks generated
reports for basic correctness before persistence.
"""

from __future__ import annotations

import datetime as dt

from ghillie.evidence.models import (
    CommitEvidence,
    RepositoryEvidenceBundle,
    RepositoryMetadata,
    ReportStatus,
)
from ghillie.reporting.validation import (
    ReportValidationResult,
    validate_repository_report,
)
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


class TestValidReportPassesChecks:
    """A well-formed result with plausible data should pass validation."""

    def test_valid_result_passes_basic_correctness_checks(self) -> None:
        bundle = _make_bundle(commit_count=3)
        result = _make_result(highlights=("Did a thing",))
        outcome = validate_repository_report(bundle, result)

        assert outcome.is_valid, f"expected valid, got issues: {outcome.issues}"


class TestRejectsEmptySummary:
    """Reports with empty or whitespace-only summaries must be rejected."""

    def test_rejects_empty_summary(self) -> None:
        bundle = _make_bundle()
        result = _make_result(summary="")
        outcome = validate_repository_report(bundle, result)

        assert not outcome.is_valid
        codes = [issue.code for issue in outcome.issues]
        assert "empty_summary" in codes

    def test_rejects_whitespace_only_summary(self) -> None:
        bundle = _make_bundle()
        result = _make_result(summary="   \n  ")
        outcome = validate_repository_report(bundle, result)

        assert not outcome.is_valid
        codes = [issue.code for issue in outcome.issues]
        assert "empty_summary" in codes


class TestRejectsObviouslyTruncatedSummary:
    """Summaries that look truncated should be rejected."""

    def test_rejects_trailing_ellipsis(self) -> None:
        bundle = _make_bundle()
        result = _make_result(summary="The repository was active and...")
        outcome = validate_repository_report(bundle, result)

        assert not outcome.is_valid
        codes = [issue.code for issue in outcome.issues]
        assert "truncated_summary" in codes

    def test_rejects_unicode_ellipsis(self) -> None:
        bundle = _make_bundle()
        result = _make_result(summary="The repository was active and\u2026")
        outcome = validate_repository_report(bundle, result)

        assert not outcome.is_valid
        codes = [issue.code for issue in outcome.issues]
        assert "truncated_summary" in codes


class TestRejectsImplausibleHighlightCount:
    """Highlight counts that are implausible relative to events."""

    def test_rejects_implausible_highlight_count_for_event_volume(self) -> None:
        """Many highlights from a bundle with very few events is suspicious."""
        bundle = _make_bundle(commit_count=1)
        # 20 highlights from 1 event is implausible
        highlights = tuple(f"Highlight {i}" for i in range(20))
        result = _make_result(highlights=highlights)
        outcome = validate_repository_report(bundle, result)

        assert not outcome.is_valid
        codes = [issue.code for issue in outcome.issues]
        assert "implausible_highlights" in codes

    def test_accepts_proportional_highlights(self) -> None:
        """Highlights proportional to events should pass."""
        bundle = _make_bundle(commit_count=10)
        result = _make_result(highlights=("Did a thing", "Did another"))
        outcome = validate_repository_report(bundle, result)

        assert outcome.is_valid


class TestValidationResultStructure:
    """ReportValidationResult exposes expected attributes."""

    def test_valid_result_has_no_issues(self) -> None:
        bundle = _make_bundle()
        result = _make_result(highlights=("One thing",))
        outcome = validate_repository_report(bundle, result)

        assert outcome.is_valid
        assert outcome.issues == ()

    def test_invalid_result_contains_issues(self) -> None:
        bundle = _make_bundle()
        result = _make_result(summary="")
        outcome = validate_repository_report(bundle, result)

        assert not outcome.is_valid
        assert len(outcome.issues) >= 1
        issue = outcome.issues[0]
        assert issue.code == "empty_summary"
        assert issue.message  # non-empty description
