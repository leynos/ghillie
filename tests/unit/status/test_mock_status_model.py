"""Unit tests for MockStatusModel implementation."""

from __future__ import annotations

import asyncio
import datetime as dt

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

    def test_open_prs_produce_review_step_singular(
        self,
        repository_metadata: RepositoryMetadata,
    ) -> None:
        """Evidence with one open PR produces 'Review 1 open PR' step."""
        evidence = RepositoryEvidenceBundle(
            repository=repository_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            pull_requests=(
                PullRequestEvidence(
                    id=100,
                    number=50,
                    title="Add feature X",
                    state="open",
                    work_type=WorkType.FEATURE,
                ),
            ),
            commits=(
                CommitEvidence(
                    sha="abc123",
                    message="feat: add feature X",
                    work_type=WorkType.FEATURE,
                ),
            ),
            work_type_groupings=(
                WorkTypeGrouping(
                    work_type=WorkType.FEATURE,
                    commit_count=1,
                    pr_count=1,
                    issue_count=0,
                ),
            ),
            generated_at=dt.datetime.now(dt.UTC),
        )

        result = _summarize(evidence)

        assert any("Review 1 open PR" in step for step in result.next_steps), (
            f"Expected 'Review 1 open PR' step, got: {result.next_steps}"
        )

    def test_open_prs_produce_review_step_plural(
        self,
        repository_metadata: RepositoryMetadata,
    ) -> None:
        """Evidence with multiple open PRs produces 'Review N open PRs' step."""
        evidence = RepositoryEvidenceBundle(
            repository=repository_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            pull_requests=(
                PullRequestEvidence(
                    id=100,
                    number=50,
                    title="Add feature X",
                    state="open",
                    work_type=WorkType.FEATURE,
                ),
                PullRequestEvidence(
                    id=101,
                    number=51,
                    title="Add feature Y",
                    state="open",
                    work_type=WorkType.FEATURE,
                ),
            ),
            commits=(
                CommitEvidence(
                    sha="abc123",
                    message="feat: add features",
                    work_type=WorkType.FEATURE,
                ),
            ),
            work_type_groupings=(
                WorkTypeGrouping(
                    work_type=WorkType.FEATURE,
                    commit_count=1,
                    pr_count=2,
                    issue_count=0,
                ),
            ),
            generated_at=dt.datetime.now(dt.UTC),
        )

        result = _summarize(evidence)

        assert any("Review 2 open PRs" in step for step in result.next_steps), (
            f"Expected 'Review 2 open PRs' step, got: {result.next_steps}"
        )

    def test_open_issues_produce_triage_step_singular(
        self,
        repository_metadata: RepositoryMetadata,
    ) -> None:
        """Evidence with one open issue produces 'Triage 1 open issue' step."""
        evidence = RepositoryEvidenceBundle(
            repository=repository_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            issues=(
                IssueEvidence(
                    id=200,
                    number=10,
                    title="Bug in login",
                    state="open",
                    work_type=WorkType.BUG,
                ),
            ),
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
                    pr_count=0,
                    issue_count=0,
                ),
            ),
            generated_at=dt.datetime.now(dt.UTC),
        )

        result = _summarize(evidence)

        assert any("Triage 1 open issue" in step for step in result.next_steps), (
            f"Expected 'Triage 1 open issue' step, got: {result.next_steps}"
        )

    def test_open_issues_produce_triage_step_plural(
        self,
        repository_metadata: RepositoryMetadata,
    ) -> None:
        """Evidence with multiple open issues produces 'Triage N open issues' step."""
        evidence = RepositoryEvidenceBundle(
            repository=repository_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            issues=(
                IssueEvidence(
                    id=200,
                    number=10,
                    title="Bug in login",
                    state="open",
                    work_type=WorkType.BUG,
                ),
                IssueEvidence(
                    id=201,
                    number=11,
                    title="Bug in logout",
                    state="open",
                    work_type=WorkType.BUG,
                ),
                IssueEvidence(
                    id=202,
                    number=12,
                    title="Bug in signup",
                    state="open",
                    work_type=WorkType.BUG,
                ),
            ),
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
                    pr_count=0,
                    issue_count=0,
                ),
            ),
            generated_at=dt.datetime.now(dt.UTC),
        )

        result = _summarize(evidence)

        assert any("Triage 3 open issues" in step for step in result.next_steps), (
            f"Expected 'Triage 3 open issues' step, got: {result.next_steps}"
        )

    def test_closed_prs_do_not_produce_review_step(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Evidence with only closed/merged PRs does not produce review step."""
        result = _summarize(feature_evidence)

        review_steps = [step for step in result.next_steps if "Review" in step]
        assert not review_steps, (
            f"Expected no Review steps for closed PRs, got: {review_steps}"
        )

    def test_closed_issues_do_not_produce_triage_step(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Evidence with only closed issues does not produce triage step."""
        result = _summarize(feature_evidence)

        triage_steps = [step for step in result.next_steps if "Triage" in step]
        assert not triage_steps, (
            f"Expected no Triage steps for closed issues, got: {triage_steps}"
        )
