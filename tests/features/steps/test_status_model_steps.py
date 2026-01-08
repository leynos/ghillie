"""Step definitions for status model BDD scenarios."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import pytest
from pytest_bdd import given, scenarios, then, when

from ghillie.evidence.models import (
    CommitEvidence,
    IssueEvidence,
    PreviousReportSummary,
    PullRequestEvidence,
    ReportStatus,
    RepositoryEvidenceBundle,
    RepositoryMetadata,
    WorkType,
    WorkTypeGrouping,
)
from ghillie.status import MockStatusModel, RepositoryStatusResult

scenarios("../status_model.feature")


# ---------------------------------------------------------------------------
# Context type
# ---------------------------------------------------------------------------


class StatusModelContext(typ.TypedDict, total=False):
    """Shared context for status model scenarios."""

    repository_metadata: RepositoryMetadata
    evidence_bundle: RepositoryEvidenceBundle
    status_result: RepositoryStatusResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def status_model_context() -> StatusModelContext:
    """Provide fresh context for each scenario."""
    return {}


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


# Helper functions


def _create_octo_reef_metadata() -> RepositoryMetadata:
    """Create standard repository metadata for octo/reef test repository."""
    return RepositoryMetadata(
        id="repo-123",
        owner="octo",
        name="reef",
        default_branch="main",
        estate_id="wildside",
    )


class EvidenceBundleBuilder:
    """Fluent builder for creating RepositoryEvidenceBundle instances.

    Provides a readable, chainable interface for constructing evidence bundles
    with sensible defaults. Each `with_*` method returns self for chaining.

    Examples
    --------
    >>> metadata = _create_octo_reef_metadata()
    >>> bundle = (
    ...     EvidenceBundleBuilder(metadata)
    ...     .with_commits((CommitEvidence(...),))
    ...     .with_event_fact_ids((1, 2, 3))
    ...     .build()
    ... )

    """

    def __init__(self, metadata: RepositoryMetadata) -> None:
        """Initialize builder with required repository metadata.

        Parameters
        ----------
        metadata
            Repository metadata for the bundle.

        """
        self._metadata = metadata
        self._window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        self._window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)
        self._commits: tuple[CommitEvidence, ...] = ()
        self._pull_requests: tuple[PullRequestEvidence, ...] = ()
        self._issues: tuple[IssueEvidence, ...] = ()
        self._work_type_groupings: tuple[WorkTypeGrouping, ...] = ()
        self._previous_reports: tuple[PreviousReportSummary, ...] = ()
        self._event_fact_ids: tuple[int, ...] = ()

    def _set_field(self, field_name: str, value: tuple) -> EvidenceBundleBuilder:
        """Set a field value and return self for method chaining.

        Parameters
        ----------
        field_name
            Name of the instance attribute to set.
        value
            Tuple value to assign to the field.

        Returns
        -------
        EvidenceBundleBuilder
            Self for method chaining.

        """
        setattr(self, field_name, value)
        return self

    def with_window(
        self, start: dt.datetime, end: dt.datetime
    ) -> EvidenceBundleBuilder:
        """Set the reporting window dates.

        Parameters
        ----------
        start
            Start of the reporting window.
        end
            End of the reporting window.

        Returns
        -------
        EvidenceBundleBuilder
            Self for method chaining.

        """
        self._window_start = start
        self._window_end = end
        return self

    def with_commits(
        self, commits: tuple[CommitEvidence, ...]
    ) -> EvidenceBundleBuilder:
        """Set commit evidence records.

        Parameters
        ----------
        commits
            Tuple of commit evidence records.

        Returns
        -------
        EvidenceBundleBuilder
            Self for method chaining.

        """
        return self._set_field("_commits", commits)

    def with_pull_requests(
        self, pull_requests: tuple[PullRequestEvidence, ...]
    ) -> EvidenceBundleBuilder:
        """Set pull request evidence records.

        Parameters
        ----------
        pull_requests
            Tuple of pull request evidence records.

        Returns
        -------
        EvidenceBundleBuilder
            Self for method chaining.

        """
        return self._set_field("_pull_requests", pull_requests)

    def with_issues(self, issues: tuple[IssueEvidence, ...]) -> EvidenceBundleBuilder:
        """Set issue evidence records.

        Parameters
        ----------
        issues
            Tuple of issue evidence records.

        Returns
        -------
        EvidenceBundleBuilder
            Self for method chaining.

        """
        return self._set_field("_issues", issues)

    def with_work_type_groupings(
        self, groupings: tuple[WorkTypeGrouping, ...]
    ) -> EvidenceBundleBuilder:
        """Set work type groupings.

        Parameters
        ----------
        groupings
            Tuple of work type groupings.

        Returns
        -------
        EvidenceBundleBuilder
            Self for method chaining.

        """
        return self._set_field("_work_type_groupings", groupings)

    def with_previous_reports(
        self, reports: tuple[PreviousReportSummary, ...]
    ) -> EvidenceBundleBuilder:
        """Set previous report summaries.

        Parameters
        ----------
        reports
            Tuple of previous report summaries.

        Returns
        -------
        EvidenceBundleBuilder
            Self for method chaining.

        """
        return self._set_field("_previous_reports", reports)

    def with_event_fact_ids(self, ids: tuple[int, ...]) -> EvidenceBundleBuilder:
        """Set event fact IDs covered by this bundle.

        Parameters
        ----------
        ids
            Tuple of event fact IDs.

        Returns
        -------
        EvidenceBundleBuilder
            Self for method chaining.

        """
        return self._set_field("_event_fact_ids", ids)

    def build(self) -> RepositoryEvidenceBundle:
        """Construct the RepositoryEvidenceBundle.

        Returns
        -------
        RepositoryEvidenceBundle
            Configured evidence bundle with generated_at set to a fixed timestamp.

        """
        return RepositoryEvidenceBundle(
            repository=self._metadata,
            window_start=self._window_start,
            window_end=self._window_end,
            commits=self._commits,
            pull_requests=self._pull_requests,
            issues=self._issues,
            work_type_groupings=self._work_type_groupings,
            previous_reports=self._previous_reports,
            event_fact_ids=self._event_fact_ids,
            generated_at=dt.datetime(2024, 7, 8, 0, 0, 1, tzinfo=dt.UTC),
        )


def _create_evidence_with_open_items(
    metadata: RepositoryMetadata,
    *,
    item_type: typ.Literal["pr", "issue"],
) -> RepositoryEvidenceBundle:
    """Create evidence bundle with open PRs or issues for testing.

    Parameters
    ----------
    metadata
        Repository metadata for the bundle.
    item_type
        Type of open items to include: "pr" for pull requests, "issue" for issues.

    Returns
    -------
    RepositoryEvidenceBundle
        Evidence bundle with specified open items.

    """
    if item_type == "pr":
        return (
            EvidenceBundleBuilder(metadata)
            .with_commits(
                (
                    CommitEvidence(
                        sha="abc123",
                        message="feat: add feature",
                        work_type=WorkType.FEATURE,
                    ),
                )
            )
            .with_pull_requests(
                (
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
                )
            )
            .with_work_type_groupings(
                (
                    WorkTypeGrouping(
                        work_type=WorkType.FEATURE,
                        commit_count=1,
                        pr_count=2,
                        issue_count=0,
                    ),
                )
            )
            .with_event_fact_ids((1, 2, 3))
            .build()
        )
    # item_type == "issue"
    return (
        EvidenceBundleBuilder(metadata)
        .with_commits(
            (
                CommitEvidence(
                    sha="abc123",
                    message="feat: add feature",
                    work_type=WorkType.FEATURE,
                ),
            )
        )
        .with_issues(
            (
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
            )
        )
        .with_work_type_groupings(
            (
                WorkTypeGrouping(
                    work_type=WorkType.FEATURE,
                    commit_count=1,
                    pr_count=0,
                    issue_count=0,
                ),
            )
        )
        .with_event_fact_ids((1, 2, 3))
        .build()
    )


@given(
    'a repository "octo/reef" with feature activity',
    target_fixture="status_model_context",
)
def given_repository_with_feature_activity(
    status_model_context: StatusModelContext,
) -> StatusModelContext:
    """Set up repository metadata with feature activity context."""
    status_model_context["repository_metadata"] = _create_octo_reef_metadata()
    return status_model_context


@given(
    'a repository "octo/reef" with a previous report at risk',
    target_fixture="status_model_context",
)
def given_repository_with_previous_at_risk(
    status_model_context: StatusModelContext,
) -> StatusModelContext:
    """Set up repository with previous at-risk report."""
    status_model_context["repository_metadata"] = _create_octo_reef_metadata()
    return status_model_context


@given(
    'a repository "octo/reef" with no activity in window',
    target_fixture="status_model_context",
)
def given_repository_with_no_activity(
    status_model_context: StatusModelContext,
) -> StatusModelContext:
    """Set up repository with no activity."""
    status_model_context["repository_metadata"] = _create_octo_reef_metadata()
    return status_model_context


@given("an evidence bundle for the reporting window")
def given_evidence_bundle_with_activity(
    status_model_context: StatusModelContext,
) -> None:
    """Create evidence bundle with feature activity."""
    metadata = status_model_context["repository_metadata"]
    status_model_context["evidence_bundle"] = (
        EvidenceBundleBuilder(metadata)
        .with_commits(
            (
                CommitEvidence(
                    sha="abc123",
                    message="feat: add new dashboard",
                    author_name="Alice",
                    committed_at=dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                    work_type=WorkType.FEATURE,
                ),
            )
        )
        .with_pull_requests(
            (
                PullRequestEvidence(
                    id=101,
                    number=42,
                    title="Add new dashboard feature",
                    author_login="alice",
                    state="merged",
                    labels=("feature",),
                    created_at=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                    merged_at=dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                    work_type=WorkType.FEATURE,
                ),
            )
        )
        .with_work_type_groupings(
            (
                WorkTypeGrouping(
                    work_type=WorkType.FEATURE,
                    commit_count=1,
                    pr_count=1,
                    issue_count=0,
                    sample_titles=("Add new dashboard feature",),
                ),
            )
        )
        .with_event_fact_ids((1, 2))
        .build()
    )


@given("an evidence bundle with previous report context")
def given_evidence_with_previous_report(
    status_model_context: StatusModelContext,
) -> None:
    """Create evidence bundle with previous at-risk report."""
    metadata = status_model_context["repository_metadata"]
    status_model_context["evidence_bundle"] = (
        EvidenceBundleBuilder(metadata)
        .with_window(
            dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            dt.datetime(2024, 7, 15, tzinfo=dt.UTC),
        )
        .with_previous_reports(
            (
                PreviousReportSummary(
                    report_id="prev-report-1",
                    window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                    window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                    status=ReportStatus.AT_RISK,
                    highlights=("Delivered API v2",),
                    risks=(
                        "Database migration incomplete",
                        "Performance regression in search",
                    ),
                    event_count=15,
                ),
            )
        )
        .with_commits(
            (
                CommitEvidence(
                    sha="new123",
                    message="feat: add search improvements",
                    work_type=WorkType.FEATURE,
                ),
            )
        )
        .with_work_type_groupings(
            (
                WorkTypeGrouping(
                    work_type=WorkType.FEATURE,
                    commit_count=1,
                    pr_count=0,
                    issue_count=0,
                ),
            )
        )
        .with_event_fact_ids((10,))
        .build()
    )


@given("an empty evidence bundle")
def given_empty_evidence_bundle(
    status_model_context: StatusModelContext,
) -> None:
    """Create evidence bundle with no events."""
    metadata = status_model_context["repository_metadata"]
    status_model_context["evidence_bundle"] = EvidenceBundleBuilder(metadata).build()


@given(
    'a repository "octo/reef" with more bugs than features',
    target_fixture="status_model_context",
)
def given_repository_with_bug_heavy_activity(
    status_model_context: StatusModelContext,
) -> StatusModelContext:
    """Set up repository metadata for bug-heavy activity scenario."""
    status_model_context["repository_metadata"] = _create_octo_reef_metadata()
    return status_model_context


@given("an evidence bundle with bug-heavy activity")
def given_evidence_with_bug_heavy_activity(
    status_model_context: StatusModelContext,
) -> None:
    """Create evidence bundle with more bugs than features."""
    metadata = status_model_context["repository_metadata"]
    status_model_context["evidence_bundle"] = (
        EvidenceBundleBuilder(metadata)
        .with_commits(
            (
                CommitEvidence(
                    sha="fix123",
                    message="fix: resolve crash on startup",
                    work_type=WorkType.BUG,
                ),
                CommitEvidence(
                    sha="fix456",
                    message="fix: correct memory leak",
                    work_type=WorkType.BUG,
                ),
            )
        )
        .with_pull_requests(
            (
                PullRequestEvidence(
                    id=102,
                    number=43,
                    title="Fix startup crash",
                    state="merged",
                    labels=("bug",),
                    work_type=WorkType.BUG,
                ),
            )
        )
        .with_work_type_groupings(
            (
                WorkTypeGrouping(
                    work_type=WorkType.BUG,
                    commit_count=2,
                    pr_count=1,
                    issue_count=0,
                    sample_titles=("Fix startup crash",),
                ),
            )
        )
        .with_event_fact_ids((5, 6, 7))
        .build()
    )


@given(
    'a repository "octo/reef" with open pull requests',
    target_fixture="status_model_context",
)
def given_repository_with_open_prs(
    status_model_context: StatusModelContext,
) -> StatusModelContext:
    """Set up repository metadata for open PRs scenario."""
    status_model_context["repository_metadata"] = _create_octo_reef_metadata()
    return status_model_context


@given("an evidence bundle with open PRs")
def given_evidence_with_open_prs(
    status_model_context: StatusModelContext,
) -> None:
    """Create evidence bundle with open pull requests."""
    metadata = status_model_context["repository_metadata"]
    status_model_context["evidence_bundle"] = _create_evidence_with_open_items(
        metadata, item_type="pr"
    )


@given(
    'a repository "octo/reef" with open issues',
    target_fixture="status_model_context",
)
def given_repository_with_open_issues(
    status_model_context: StatusModelContext,
) -> StatusModelContext:
    """Set up repository metadata for open issues scenario."""
    status_model_context["repository_metadata"] = _create_octo_reef_metadata()
    return status_model_context


@given("an evidence bundle with open issues")
def given_evidence_with_open_issues(
    status_model_context: StatusModelContext,
) -> None:
    """Create evidence bundle with open issues."""
    metadata = status_model_context["repository_metadata"]
    status_model_context["evidence_bundle"] = _create_evidence_with_open_items(
        metadata, item_type="issue"
    )


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("I summarize the evidence bundle using the mock status model")
def when_summarize_with_mock(status_model_context: StatusModelContext) -> None:
    """Run the mock status model on the evidence bundle."""

    async def _summarize() -> RepositoryStatusResult:
        model = MockStatusModel()
        return await model.summarize_repository(status_model_context["evidence_bundle"])

    status_model_context["status_result"] = asyncio.run(_summarize())


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then('the status result has status "on_track"')
def then_status_is_on_track(status_model_context: StatusModelContext) -> None:
    """Verify status is ON_TRACK."""
    assert status_model_context["status_result"].status == ReportStatus.ON_TRACK


@then('the status result has status "at_risk"')
def then_status_is_at_risk(status_model_context: StatusModelContext) -> None:
    """Verify status is AT_RISK."""
    assert status_model_context["status_result"].status == ReportStatus.AT_RISK


@then('the status result has status "unknown"')
def then_status_is_unknown(status_model_context: StatusModelContext) -> None:
    """Verify status is UNKNOWN."""
    assert status_model_context["status_result"].status == ReportStatus.UNKNOWN


@then("the status result summary mentions the repository slug")
def then_summary_mentions_slug(status_model_context: StatusModelContext) -> None:
    """Verify summary contains repository slug."""
    result = status_model_context["status_result"]
    assert "octo/reef" in result.summary


@then("the status result contains highlights")
def then_result_has_highlights(status_model_context: StatusModelContext) -> None:
    """Verify result contains highlights."""
    result = status_model_context["status_result"]
    assert len(result.highlights) > 0


@then("the status result risks include ongoing risks from previous report")
def then_risks_include_ongoing(status_model_context: StatusModelContext) -> None:
    """Verify risks reference ongoing items from previous report."""
    result = status_model_context["status_result"]
    assert len(result.risks) > 0
    ongoing_risks = [r for r in result.risks if "ongoing" in r.lower()]
    assert len(ongoing_risks) > 0


@then("the status result summary indicates no activity")
def then_summary_indicates_no_activity(
    status_model_context: StatusModelContext,
) -> None:
    """Verify summary indicates no activity."""
    result = status_model_context["status_result"]
    assert "no recorded activity" in result.summary.lower()


@then("the next steps include addressing risks")
def then_next_steps_include_addressing_risks(
    status_model_context: StatusModelContext,
) -> None:
    """Verify next steps include a step about addressing risks."""
    result = status_model_context["status_result"]
    assert result.next_steps, "Expected at least one next step"
    assert any("risk" in step.lower() for step in result.next_steps), (
        f"Expected a risk-focused next step, got: {result.next_steps}"
    )


@then("the next steps include investigating activity")
def then_next_steps_include_investigating(
    status_model_context: StatusModelContext,
) -> None:
    """Verify next steps include an investigation step."""
    result = status_model_context["status_result"]
    assert result.next_steps, "Expected at least one next step"
    assert any("investigat" in step.lower() for step in result.next_steps), (
        f"Expected an investigation-focused next step, got: {result.next_steps}"
    )


def _assert_next_step_keywords(
    result: RepositoryStatusResult,
    keywords: tuple[str, ...],
    item_description: str,
) -> None:
    """Assert that at least one next step contains all specified keywords.

    Parameters
    ----------
    result
        The repository status result to check.
    keywords
        Tuple of keywords that must all appear in a single next step.
    item_description
        Human-readable description for error messages.

    Raises
    ------
    AssertionError
        If no next steps exist or no step contains all keywords.

    """
    assert result.next_steps, "Expected at least one next step"
    assert any(
        all(kw in step.lower() for kw in keywords) for step in result.next_steps
    ), f"Expected a {item_description} step, got: {result.next_steps}"


@then("the next steps include reviewing open PRs")
def then_next_steps_include_review_prs(
    status_model_context: StatusModelContext,
) -> None:
    """Verify next steps include reviewing open PRs."""
    result = status_model_context["status_result"]
    _assert_next_step_keywords(result, ("review", "open", "pr"), "PR review")


@then("the next steps include triaging open issues")
def then_next_steps_include_triage_issues(
    status_model_context: StatusModelContext,
) -> None:
    """Verify next steps include triaging open issues."""
    result = status_model_context["status_result"]
    _assert_next_step_keywords(result, ("triage", "open", "issue"), "issue triage")
