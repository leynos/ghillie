"""Shared fixtures for status model tests."""

from __future__ import annotations

import datetime as dt

import pytest

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


@pytest.fixture
def repository_metadata() -> RepositoryMetadata:
    """Provide basic repository metadata for tests."""
    return RepositoryMetadata(
        id="repo-123",
        owner="octo",
        name="reef",
        default_branch="main",
        estate_id="wildside",
    )


@pytest.fixture
def empty_evidence(repository_metadata: RepositoryMetadata) -> RepositoryEvidenceBundle:
    """Provide an empty evidence bundle with no events."""
    return RepositoryEvidenceBundle(
        repository=repository_metadata,
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        generated_at=dt.datetime(2024, 7, 8, 0, 0, 1, tzinfo=dt.UTC),
    )


@pytest.fixture
def feature_evidence(
    repository_metadata: RepositoryMetadata,
) -> RepositoryEvidenceBundle:
    """Provide evidence bundle with feature activity."""
    return RepositoryEvidenceBundle(
        repository=repository_metadata,
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
            CommitEvidence(
                sha="def456",
                message="docs: update readme",
                author_name="Bob",
                committed_at=dt.datetime(2024, 7, 3, tzinfo=dt.UTC),
                work_type=WorkType.DOCUMENTATION,
            ),
        ),
        pull_requests=(
            PullRequestEvidence(
                id=101,
                number=42,
                title="Add new dashboard feature",
                author_login="alice",
                state="merged",
                labels=("feature", "enhancement"),
                created_at=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                merged_at=dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                work_type=WorkType.FEATURE,
            ),
        ),
        issues=(
            IssueEvidence(
                id=201,
                number=10,
                title="Track dashboard metrics",
                author_login="charlie",
                state="closed",
                labels=("feature",),
                created_at=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                closed_at=dt.datetime(2024, 7, 3, tzinfo=dt.UTC),
                work_type=WorkType.FEATURE,
            ),
        ),
        work_type_groupings=(
            WorkTypeGrouping(
                work_type=WorkType.FEATURE,
                commit_count=1,
                pr_count=1,
                issue_count=1,
                sample_titles=("Add new dashboard feature",),
            ),
            WorkTypeGrouping(
                work_type=WorkType.DOCUMENTATION,
                commit_count=1,
                pr_count=0,
                issue_count=0,
                sample_titles=(),
            ),
        ),
        event_fact_ids=(1, 2, 3, 4),
        generated_at=dt.datetime(2024, 7, 8, 0, 0, 1, tzinfo=dt.UTC),
    )


@pytest.fixture
def bug_heavy_evidence(
    repository_metadata: RepositoryMetadata,
) -> RepositoryEvidenceBundle:
    """Provide evidence bundle with more bugs than features."""
    return RepositoryEvidenceBundle(
        repository=repository_metadata,
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        commits=(
            CommitEvidence(
                sha="fix123",
                message="fix: resolve crash on startup",
                author_name="Dave",
                author_email="dave@example.com",
                committed_at=dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                work_type=WorkType.BUG,
            ),
            CommitEvidence(
                sha="fix456",
                message="fix: correct memory leak",
                author_name="Eve",
                author_email="eve@example.com",
                committed_at=dt.datetime(2024, 7, 3, tzinfo=dt.UTC),
                work_type=WorkType.BUG,
            ),
        ),
        pull_requests=(
            PullRequestEvidence(
                id=102,
                number=43,
                title="Fix startup crash",
                author_login="dave",
                state="merged",
                labels=("bug",),
                created_at=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                merged_at=dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                work_type=WorkType.BUG,
            ),
        ),
        issues=(
            IssueEvidence(
                id=202,
                number=11,
                title="Application crashes on startup",
                author_login="frank",
                state="open",
                labels=("bug",),
                created_at=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                work_type=WorkType.BUG,
            ),
        ),
        work_type_groupings=(
            WorkTypeGrouping(
                work_type=WorkType.BUG,
                commit_count=2,
                pr_count=1,
                issue_count=1,
                sample_titles=("Fix startup crash",),
            ),
        ),
        event_fact_ids=(5, 6, 7, 8),
        generated_at=dt.datetime(2024, 7, 8, 0, 0, 1, tzinfo=dt.UTC),
    )


@pytest.fixture
def evidence_with_previous_risks(
    repository_metadata: RepositoryMetadata,
) -> RepositoryEvidenceBundle:
    """Provide evidence bundle with previous report containing risks."""
    return RepositoryEvidenceBundle(
        repository=repository_metadata,
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
                author_name="Grace",
                author_email="grace@example.com",
                committed_at=dt.datetime(2024, 7, 9, tzinfo=dt.UTC),
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
        generated_at=dt.datetime(2024, 7, 15, 0, 0, 1, tzinfo=dt.UTC),
    )
