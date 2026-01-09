"""Unit tests for MockStatusModel implementation."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import pytest

from ghillie.evidence.models import (
    CommitEvidence,
    IssueEvidence,
    PullRequestEvidence,
    ReportStatus,
    RepositoryEvidenceBundle,
    RepositoryMetadata,
    WorkType,
    WorkTypeGrouping,
)
from ghillie.status import MockStatusModel, RepositoryStatusResult


def _summarize(evidence: RepositoryEvidenceBundle) -> RepositoryStatusResult:
    """Run MockStatusModel on evidence and return the result.

    Helper function for test classes to avoid duplication.

    Parameters
    ----------
    evidence
        The repository evidence bundle to summarize.

    Returns
    -------
    RepositoryStatusResult
        The status result from the mock model.

    """
    model = MockStatusModel()
    return asyncio.run(model.summarize_repository(evidence))


def _create_evidence_with_open_items(
    metadata: RepositoryMetadata,
    *,
    item_type: typ.Literal["pr", "issue"],
    count: int,
) -> RepositoryEvidenceBundle:
    """Create an evidence bundle with the specified number of open PRs or issues.

    Parameters
    ----------
    metadata
        Repository metadata to use for the bundle.
    item_type
        Type of item to create: "pr" for pull requests, "issue" for issues.
    count
        Number of open items to include in the bundle.

    Returns
    -------
    RepositoryEvidenceBundle
        Evidence bundle with the specified number of open PRs or issues.

    Notes
    -----
    When ``item_type`` is "pr", generates PRs with IDs starting at 100,
    numbers starting at 50, and titles "Add feature X", "Add feature Y", etc.

    When ``item_type`` is "issue", generates issues with IDs starting at 200,
    numbers starting at 10, and titles from a predefined list of bug descriptions.

    """
    if item_type == "pr":
        prs = tuple(
            PullRequestEvidence(
                id=100 + i,
                number=50 + i,
                title=f"Add feature {chr(88 + i)}",
                state="open",
                work_type=WorkType.FEATURE,
            )
            for i in range(count)
        )
        issues: tuple[IssueEvidence, ...] = ()
        pr_count = count
    else:
        issue_titles = ["Bug in login", "Bug in logout", "Bug in signup"]
        issues = tuple(
            IssueEvidence(
                id=200 + i,
                number=10 + i,
                title=issue_titles[i] if i < len(issue_titles) else f"Bug {i + 1}",
                state="open",
                work_type=WorkType.BUG,
            )
            for i in range(count)
        )
        prs: tuple[PullRequestEvidence, ...] = ()
        pr_count = 0

    return RepositoryEvidenceBundle(
        repository=metadata,
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        pull_requests=prs,
        issues=issues,
        commits=(
            CommitEvidence(
                sha="abc123",
                message="feat: add feature",
                work_type=WorkType.FEATURE,
            ),
        ),
        work_type_groupings=(
            WorkTypeGrouping(
                work_type=WorkType.FEATURE,
                commit_count=1,
                pr_count=pr_count,
                issue_count=0,
            ),
        ),
        generated_at=dt.datetime(2024, 7, 8, 0, 0, 1, tzinfo=dt.UTC),
    )


def _assert_no_next_steps_containing(
    result: RepositoryStatusResult,
    keyword: str,
    item_description: str,
) -> None:
    """Assert that no next steps contain the specified keyword.

    Parameters
    ----------
    result
        The repository status result to check.
    keyword
        The keyword to search for in next steps.
    item_description
        Description of the item type for the error message.

    """
    matching_steps = [step for step in result.next_steps if keyword in step]
    assert not matching_steps, (
        f"Expected no {item_description} steps for closed items, got: {matching_steps}"
    )


class TestMockStatusModelHeuristics:
    """Tests for MockStatusModel deterministic heuristics."""

    def test_returns_unknown_for_empty_evidence(
        self,
        empty_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock returns UNKNOWN when evidence bundle has no events."""
        result = _summarize(empty_evidence)

        assert result.status == ReportStatus.UNKNOWN

    def test_returns_on_track_for_feature_activity(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock returns ON_TRACK for normal feature activity."""
        result = _summarize(feature_evidence)

        assert result.status == ReportStatus.ON_TRACK

    def test_returns_at_risk_when_bugs_exceed_features(
        self,
        bug_heavy_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock returns AT_RISK when bug activity exceeds features."""
        result = _summarize(bug_heavy_evidence)

        assert result.status == ReportStatus.AT_RISK

    def test_returns_at_risk_when_previous_risks_exist(
        self,
        evidence_with_previous_risks: RepositoryEvidenceBundle,
    ) -> None:
        """Mock returns AT_RISK when previous report had risks and AT_RISK status."""
        result = _summarize(evidence_with_previous_risks)

        assert result.status == ReportStatus.AT_RISK


class TestMockStatusModelOutput:
    """Tests for MockStatusModel output content quality."""

    def test_summary_mentions_repository(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock generates summary mentioning repository slug."""
        result = _summarize(feature_evidence)

        assert "octo/reef" in result.summary

    def test_summary_includes_event_counts(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock generates summary with event counts."""
        result = _summarize(feature_evidence)

        # Evidence has 2 commits, 1 PR, 1 issue
        assert "2 commits" in result.summary
        assert "1 pull request" in result.summary
        assert "1 issue" in result.summary

    def test_summary_indicates_no_activity_when_empty(
        self,
        empty_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock generates appropriate summary for empty evidence."""
        result = _summarize(empty_evidence)

        assert "no recorded activity" in result.summary.lower()

    def test_extracts_highlights_from_features(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock extracts highlights from feature work."""
        result = _summarize(feature_evidence)

        # Should have highlight about delivered PRs
        assert len(result.highlights) > 0

    def test_carries_forward_previous_risks(
        self,
        evidence_with_previous_risks: RepositoryEvidenceBundle,
    ) -> None:
        """Mock carries forward risks from previous reports."""
        result = _summarize(evidence_with_previous_risks)

        # Should reference ongoing risks
        assert len(result.risks) > 0
        # At least one risk should be marked as ongoing
        ongoing_risks = [r for r in result.risks if "ongoing" in r.lower()]
        assert len(ongoing_risks) > 0


class TestMockStatusModelNextSteps:
    """Tests for MockStatusModel next_steps suggestions."""

    def test_at_risk_includes_mitigation_step(
        self,
        evidence_with_previous_risks: RepositoryEvidenceBundle,
    ) -> None:
        """AT_RISK status includes a step to address identified risks."""
        result = _summarize(evidence_with_previous_risks)

        assert result.status == ReportStatus.AT_RISK
        assert result.next_steps, "Expected at least one next step for AT_RISK status"
        assert any("risk" in step.lower() for step in result.next_steps), (
            f"Expected a risk-focused next step, got: {result.next_steps}"
        )

    def test_unknown_includes_investigation_step(
        self,
        empty_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """UNKNOWN status with no activity includes an investigation step."""
        result = _summarize(empty_evidence)

        assert result.status == ReportStatus.UNKNOWN
        assert result.next_steps, "Expected at least one next step for UNKNOWN status"
        assert any("investigat" in step.lower() for step in result.next_steps), (
            f"Expected an investigation-focused next step, got: {result.next_steps}"
        )

    @pytest.mark.parametrize(
        ("item_type", "count", "expected_step"),
        [
            pytest.param("pr", 1, "Review 1 open PR", id="prs_singular"),
            pytest.param("pr", 2, "Review 2 open PRs", id="prs_plural"),
            pytest.param("issue", 1, "Triage 1 open issue", id="issues_singular"),
            pytest.param("issue", 3, "Triage 3 open issues", id="issues_plural"),
        ],
    )
    def test_open_items_produce_expected_next_step(
        self,
        repository_metadata: RepositoryMetadata,
        item_type: typ.Literal["pr", "issue"],
        count: int,
        expected_step: str,
    ) -> None:
        """Open PRs/issues produce appropriate review/triage next steps."""
        evidence = _create_evidence_with_open_items(
            repository_metadata, item_type=item_type, count=count
        )

        result = _summarize(evidence)

        assert any(expected_step in step for step in result.next_steps), (
            f"Expected '{expected_step}' step, got: {result.next_steps}"
        )

    def test_closed_prs_do_not_produce_review_step(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Evidence with only closed/merged PRs does not produce review step."""
        result = _summarize(feature_evidence)

        _assert_no_next_steps_containing(result, "Review", "PR review")

    def test_closed_issues_do_not_produce_triage_step(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Evidence with only closed issues does not produce triage step."""
        result = _summarize(feature_evidence)

        _assert_no_next_steps_containing(result, "Triage", "issue triage")
