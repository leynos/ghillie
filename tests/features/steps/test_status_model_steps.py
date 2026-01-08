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
    status_model_context["evidence_bundle"] = RepositoryEvidenceBundle(
        repository=metadata,
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        commits=(
            CommitEvidence(
                sha="abc123",
                message="feat: add new dashboard",
                author_name="Alice",
                committed_at=dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                work_type=WorkType.FEATURE,
            ),
        ),
        pull_requests=(
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
        ),
        work_type_groupings=(
            WorkTypeGrouping(
                work_type=WorkType.FEATURE,
                commit_count=1,
                pr_count=1,
                issue_count=0,
                sample_titles=("Add new dashboard feature",),
            ),
        ),
        event_fact_ids=(1, 2),
        generated_at=dt.datetime.now(dt.UTC),
    )


@given("an evidence bundle with previous report context")
def given_evidence_with_previous_report(
    status_model_context: StatusModelContext,
) -> None:
    """Create evidence bundle with previous at-risk report."""
    metadata = status_model_context["repository_metadata"]
    status_model_context["evidence_bundle"] = RepositoryEvidenceBundle(
        repository=metadata,
        window_start=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 15, tzinfo=dt.UTC),
        previous_reports=(
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
        ),
        commits=(
            CommitEvidence(
                sha="new123",
                message="feat: add search improvements",
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
        event_fact_ids=(10,),
        generated_at=dt.datetime.now(dt.UTC),
    )


@given("an empty evidence bundle")
def given_empty_evidence_bundle(
    status_model_context: StatusModelContext,
) -> None:
    """Create evidence bundle with no events."""
    metadata = status_model_context["repository_metadata"]
    status_model_context["evidence_bundle"] = RepositoryEvidenceBundle(
        repository=metadata,
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        generated_at=dt.datetime.now(dt.UTC),
    )


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
    status_model_context["evidence_bundle"] = RepositoryEvidenceBundle(
        repository=metadata,
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        commits=(
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
        ),
        pull_requests=(
            PullRequestEvidence(
                id=102,
                number=43,
                title="Fix startup crash",
                state="merged",
                labels=("bug",),
                work_type=WorkType.BUG,
            ),
        ),
        work_type_groupings=(
            WorkTypeGrouping(
                work_type=WorkType.BUG,
                commit_count=2,
                pr_count=1,
                issue_count=0,
                sample_titles=("Fix startup crash",),
            ),
        ),
        event_fact_ids=(5, 6, 7),
        generated_at=dt.datetime.now(dt.UTC),
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
    status_model_context["evidence_bundle"] = RepositoryEvidenceBundle(
        repository=metadata,
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        commits=(
            CommitEvidence(
                sha="abc123",
                message="feat: add feature X",
                work_type=WorkType.FEATURE,
            ),
        ),
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
        work_type_groupings=(
            WorkTypeGrouping(
                work_type=WorkType.FEATURE,
                commit_count=1,
                pr_count=2,
                issue_count=0,
            ),
        ),
        event_fact_ids=(1, 2, 3),
        generated_at=dt.datetime.now(dt.UTC),
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
    status_model_context["evidence_bundle"] = RepositoryEvidenceBundle(
        repository=metadata,
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        commits=(
            CommitEvidence(
                sha="abc123",
                message="feat: add feature",
                work_type=WorkType.FEATURE,
            ),
        ),
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
        ),
        work_type_groupings=(
            WorkTypeGrouping(
                work_type=WorkType.FEATURE,
                commit_count=1,
                pr_count=0,
                issue_count=0,
            ),
        ),
        event_fact_ids=(1, 2, 3),
        generated_at=dt.datetime.now(dt.UTC),
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


@then("the next steps include reviewing open PRs")
def then_next_steps_include_review_prs(
    status_model_context: StatusModelContext,
) -> None:
    """Verify next steps include reviewing open PRs."""
    result = status_model_context["status_result"]
    assert result.next_steps, "Expected at least one next step"
    assert any(
        "review" in step.lower() and "open" in step.lower() and "pr" in step.lower()
        for step in result.next_steps
    ), f"Expected a PR review step, got: {result.next_steps}"


@then("the next steps include triaging open issues")
def then_next_steps_include_triage_issues(
    status_model_context: StatusModelContext,
) -> None:
    """Verify next steps include triaging open issues."""
    result = status_model_context["status_result"]
    assert result.next_steps, "Expected at least one next step"
    assert any(
        "triage" in step.lower() and "open" in step.lower() and "issue" in step.lower()
        for step in result.next_steps
    ), f"Expected an issue triage step, got: {result.next_steps}"
