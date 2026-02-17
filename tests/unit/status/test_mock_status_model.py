"""Unit tests for MockStatusModel implementation.

This module provides comprehensive tests for the MockStatusModel class, which
serves as a deterministic, offline implementation of the RepositoryStatusModel
protocol. The mock model uses simple heuristics to generate status reports
without requiring external LLM services, making it suitable for testing,
development, and demonstration purposes.

Test Coverage
-------------
The tests validate several aspects of MockStatusModel behaviour:

- **Heuristics**: Verifies the deterministic logic for status determination
  (e.g., ON_TRACK for normal activity, AT_RISK when bugs exceed features).
- **Output quality**: Ensures generated summaries, highlights, and risks
  contain appropriate content derived from the evidence bundle.
- **Next steps**: Validates that actionable recommendations are generated
  based on open PRs, issues, and overall repository status.

Fixtures
--------
Tests rely on shared fixtures from ``conftest.py``:

- ``repository_metadata``: Basic repository identification.
- ``empty_evidence``: Bundle with no activity (triggers UNKNOWN status).
- ``feature_evidence``: Normal feature development activity.
- ``bug_heavy_evidence``: Activity dominated by bug fixes.
- ``evidence_with_previous_risks``: Bundle with prior AT_RISK report.

Example:
-------
Running the tests::

    pytest tests/unit/status/test_mock_status_model.py -v

"""

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


def _summarise(evidence: RepositoryEvidenceBundle) -> RepositoryStatusResult:
    """Run MockStatusModel on evidence and return the result.

    Helper function for test classes to avoid duplication.

    Parameters
    ----------
    evidence
        The repository evidence bundle to summarise.

    Returns
    -------
    RepositoryStatusResult
        The status result from the mock model.

    """
    model = MockStatusModel()
    return asyncio.run(model.summarize_repository(evidence))


def _create_open_prs_tuple(count: int) -> tuple[PullRequestEvidence, ...]:
    """Create a tuple of open pull request evidence items.

    Parameters
    ----------
    count
        Number of open PRs to create.

    Returns
    -------
    tuple[PullRequestEvidence, ...]
        Tuple containing the specified number of open PRs.

    Notes
    -----
    Generates PRs with IDs starting at 100, numbers starting at 50,
    and titles "Add feature 1", "Add feature 2", etc.

    """
    return tuple(
        PullRequestEvidence(
            id=100 + i,
            number=50 + i,
            title=f"Add feature {i + 1}",
            state="open",
            work_type=WorkType.FEATURE,
        )
        for i in range(count)
    )


def _create_open_issues_tuple(count: int) -> tuple[IssueEvidence, ...]:
    """Create a tuple of open issue evidence items.

    Parameters
    ----------
    count
        Number of open issues to create.

    Returns
    -------
    tuple[IssueEvidence, ...]
        Tuple containing the specified number of open issues.

    Notes
    -----
    Generates issues with IDs starting at 200, numbers starting at 10,
    and titles from a predefined list of bug descriptions.

    """
    issue_titles = ["Bug in login", "Bug in logout", "Bug in signup"]
    return tuple(
        IssueEvidence(
            id=200 + i,
            number=10 + i,
            title=issue_titles[i] if i < len(issue_titles) else f"Bug {i + 1}",
            state="open",
            work_type=WorkType.BUG,
        )
        for i in range(count)
    )


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
    numbers starting at 50, and titles "Add feature 1", "Add feature 2", etc.

    When ``item_type`` is "issue", generates issues with IDs starting at 200,
    numbers starting at 10, and titles from a predefined list of bug descriptions.

    """
    prs: tuple[PullRequestEvidence, ...] = ()
    issues: tuple[IssueEvidence, ...] = ()
    pr_count = 0
    issue_count = 0

    match item_type:
        case "pr":
            prs = _create_open_prs_tuple(count)
            pr_count = count
            work_type = WorkType.FEATURE
        case "issue":
            issues = _create_open_issues_tuple(count)
            issue_count = count
            work_type = WorkType.BUG

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
                work_type=work_type,
                commit_count=1,
                pr_count=pr_count,
                issue_count=issue_count,
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
    keyword_cf = keyword.casefold()
    matching_steps = [
        step for step in result.next_steps if keyword_cf in step.casefold()
    ]
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
        result = _summarise(empty_evidence)

        assert result.status == ReportStatus.UNKNOWN

    def test_returns_on_track_for_feature_activity(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock returns ON_TRACK for normal feature activity."""
        result = _summarise(feature_evidence)

        assert result.status == ReportStatus.ON_TRACK

    def test_returns_at_risk_when_bugs_exceed_features(
        self,
        bug_heavy_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock returns AT_RISK when bug activity exceeds features."""
        result = _summarise(bug_heavy_evidence)

        assert result.status == ReportStatus.AT_RISK

    def test_returns_at_risk_when_previous_risks_exist(
        self,
        evidence_with_previous_risks: RepositoryEvidenceBundle,
    ) -> None:
        """Mock returns AT_RISK when previous report had risks and AT_RISK status."""
        result = _summarise(evidence_with_previous_risks)

        assert result.status == ReportStatus.AT_RISK


class TestMockStatusModelOutput:
    """Tests for MockStatusModel output content quality."""

    def test_summary_mentions_repository(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock generates summary mentioning repository slug."""
        result = _summarise(feature_evidence)

        expected_slug = feature_evidence.repository.slug
        assert expected_slug in result.summary

    def test_summary_includes_event_counts(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock generates summary with event counts."""
        result = _summarise(feature_evidence)

        commit_count = len(feature_evidence.commits)
        pr_count = len(feature_evidence.pull_requests)
        issue_count = len(feature_evidence.issues)

        assert f"{commit_count} commit" in result.summary
        assert f"{pr_count} pull request" in result.summary
        assert f"{issue_count} issue" in result.summary

    def test_summary_indicates_no_activity_when_empty(
        self,
        empty_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock generates appropriate summary for empty evidence."""
        result = _summarise(empty_evidence)

        assert "no recorded activity" in result.summary.casefold()

    def test_extracts_highlights_from_features(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock extracts highlights from feature work."""
        result = _summarise(feature_evidence)

        # Should have highlight about delivered PRs
        assert len(result.highlights) > 0

    def test_carries_forward_previous_risks(
        self,
        evidence_with_previous_risks: RepositoryEvidenceBundle,
    ) -> None:
        """Mock carries forward risks from previous reports."""
        result = _summarise(evidence_with_previous_risks)

        # Should reference ongoing risks
        assert len(result.risks) > 0
        # At least one risk should be marked as ongoing
        ongoing_risks = [r for r in result.risks if "ongoing" in r.casefold()]
        assert len(ongoing_risks) > 0


class StatusNextStepTestCase(typ.NamedTuple):
    """Test case parameters for status next step validation."""

    evidence_fixture: str
    expected_status: ReportStatus
    keyword: str
    description: str


class TestMockStatusModelNextSteps:
    """Tests for MockStatusModel next_steps suggestions."""

    @pytest.mark.parametrize(
        "test_case",
        [
            pytest.param(
                StatusNextStepTestCase(
                    evidence_fixture="evidence_with_previous_risks",
                    expected_status=ReportStatus.AT_RISK,
                    keyword="risk",
                    description="risk-focused",
                ),
                id="at_risk_includes_mitigation_step",
            ),
            pytest.param(
                StatusNextStepTestCase(
                    evidence_fixture="empty_evidence",
                    expected_status=ReportStatus.UNKNOWN,
                    keyword="investigat",
                    description="investigation-focused",
                ),
                id="unknown_includes_investigation_step",
            ),
        ],
    )
    def test_status_includes_appropriate_next_step(
        self,
        request: pytest.FixtureRequest,
        test_case: StatusNextStepTestCase,
    ) -> None:
        """Specific status codes include appropriate next step guidance."""
        evidence = request.getfixturevalue(test_case.evidence_fixture)

        result = _summarise(evidence)

        assert result.status == test_case.expected_status
        assert result.next_steps, (
            f"Expected at least one next step for "
            f"{test_case.expected_status.value} status"
        )
        assert any(
            test_case.keyword in step.casefold() for step in result.next_steps
        ), f"Expected a {test_case.description} next step, got: {result.next_steps}"

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

        result = _summarise(evidence)

        assert any(expected_step in step for step in result.next_steps), (
            f"Expected '{expected_step}' step, got: {result.next_steps}"
        )

    def test_closed_prs_do_not_produce_review_step(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Evidence with only closed/merged PRs does not produce review step."""
        result = _summarise(feature_evidence)

        _assert_no_next_steps_containing(result, "Review", "PR review")

    def test_closed_issues_do_not_produce_triage_step(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Evidence with only closed issues does not produce triage step."""
        result = _summarise(feature_evidence)

        _assert_no_next_steps_containing(result, "Triage", "issue triage")


class TestMockStatusModelInvocationMetrics:
    """Tests for invocation metrics exposed by ``MockStatusModel``."""

    def test_metrics_none_before_first_call(self) -> None:
        """No metrics should be available before invocation."""
        model = MockStatusModel()
        assert model.last_invocation_metrics is None

    def test_metrics_set_to_zero_tokens_after_call(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock model reports zero-token usage after summarization."""
        model = MockStatusModel()

        asyncio.run(model.summarize_repository(feature_evidence))

        metrics = model.last_invocation_metrics
        assert metrics is not None
        assert metrics.prompt_tokens == 0
        assert metrics.completion_tokens == 0
        assert metrics.total_tokens == 0
