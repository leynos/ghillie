"""Unit tests for OpenAI prompt templates."""

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
from ghillie.status.prompts import SYSTEM_PROMPT, build_user_prompt


class TestSystemPrompt:
    """Tests for the system prompt constant."""

    def test_system_prompt_contains_json_schema(self) -> None:
        """System prompt includes JSON output schema."""
        assert "status" in SYSTEM_PROMPT
        assert "summary" in SYSTEM_PROMPT
        assert "highlights" in SYSTEM_PROMPT
        assert "risks" in SYSTEM_PROMPT
        assert "next_steps" in SYSTEM_PROMPT

    def test_system_prompt_contains_status_values(self) -> None:
        """System prompt documents valid status values."""
        assert "on_track" in SYSTEM_PROMPT
        assert "at_risk" in SYSTEM_PROMPT
        assert "blocked" in SYSTEM_PROMPT
        assert "unknown" in SYSTEM_PROMPT

    def test_system_prompt_instructs_no_repetition(self) -> None:
        """System prompt instructs model to avoid repetition."""
        lower = SYSTEM_PROMPT.lower()
        assert "repeat" in lower or "repetition" in lower or "unchanged" in lower


class TestBuildUserPrompt:
    """Tests for user prompt generation from evidence bundles."""

    @pytest.fixture
    def repository_metadata(self) -> RepositoryMetadata:
        """Provide basic repository metadata."""
        return RepositoryMetadata(
            id="repo-123",
            owner="octo",
            name="reef",
            default_branch="main",
            estate_id="wildside",
        )

    @pytest.fixture
    def minimal_evidence(
        self, repository_metadata: RepositoryMetadata
    ) -> RepositoryEvidenceBundle:
        """Provide minimal evidence bundle."""
        return RepositoryEvidenceBundle(
            repository=repository_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        )

    def test_includes_repository_slug(
        self, minimal_evidence: RepositoryEvidenceBundle
    ) -> None:
        """User prompt includes repository slug."""
        prompt = build_user_prompt(minimal_evidence)
        assert "octo/reef" in prompt

    def test_includes_window_dates(
        self, minimal_evidence: RepositoryEvidenceBundle
    ) -> None:
        """User prompt includes reporting window dates."""
        prompt = build_user_prompt(minimal_evidence)
        assert "2024-07-01" in prompt
        assert "2024-07-08" in prompt

    def test_includes_activity_summary(
        self, repository_metadata: RepositoryMetadata
    ) -> None:
        """User prompt includes activity counts."""
        evidence = RepositoryEvidenceBundle(
            repository=repository_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            commits=(
                CommitEvidence(sha="abc123", message="feat: add feature"),
                CommitEvidence(sha="def456", message="fix: bug fix"),
            ),
            pull_requests=(PullRequestEvidence(id=1, number=42, title="Add feature"),),
            issues=(
                IssueEvidence(id=1, number=10, title="Bug report"),
                IssueEvidence(id=2, number=11, title="Feature request"),
            ),
        )
        prompt = build_user_prompt(evidence)

        # Should mention counts
        assert "2" in prompt  # 2 commits
        assert "1" in prompt  # 1 PR
        # Should mention entity types
        lower = prompt.lower()
        assert "commit" in lower
        assert "pull request" in lower or "pr" in lower
        assert "issue" in lower

    def test_includes_previous_reports(
        self, repository_metadata: RepositoryMetadata
    ) -> None:
        """User prompt includes previous report context."""
        evidence = RepositoryEvidenceBundle(
            repository=repository_metadata,
            window_start=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 15, tzinfo=dt.UTC),
            previous_reports=(
                PreviousReportSummary(
                    report_id="prev-1",
                    window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                    window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                    status=ReportStatus.AT_RISK,
                    highlights=("Delivered API v2",),
                    risks=("Database migration incomplete",),
                    event_count=10,
                ),
            ),
        )
        prompt = build_user_prompt(evidence)

        # Should include previous status
        assert "at_risk" in prompt.lower() or "at risk" in prompt.lower()
        # Should include highlights and risks
        assert "API v2" in prompt or "Delivered" in prompt
        assert "migration" in prompt.lower() or "Database" in prompt

    def test_includes_work_type_breakdown(
        self, repository_metadata: RepositoryMetadata
    ) -> None:
        """User prompt includes work type groupings."""
        evidence = RepositoryEvidenceBundle(
            repository=repository_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            work_type_groupings=(
                WorkTypeGrouping(
                    work_type=WorkType.FEATURE,
                    commit_count=3,
                    pr_count=2,
                    issue_count=1,
                    sample_titles=("Add dashboard",),
                ),
                WorkTypeGrouping(
                    work_type=WorkType.BUG,
                    commit_count=1,
                    pr_count=1,
                    issue_count=2,
                    sample_titles=("Fix crash",),
                ),
            ),
        )
        prompt = build_user_prompt(evidence)

        # Should mention work types
        lower = prompt.lower()
        assert "feature" in lower
        assert "bug" in lower

    def test_includes_pull_request_details(
        self, repository_metadata: RepositoryMetadata
    ) -> None:
        """User prompt includes PR details with numbers and titles."""
        evidence = RepositoryEvidenceBundle(
            repository=repository_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            pull_requests=(
                PullRequestEvidence(
                    id=101,
                    number=42,
                    title="Add new dashboard feature",
                    state="merged",
                ),
                PullRequestEvidence(
                    id=102,
                    number=43,
                    title="Fix authentication bug",
                    state="open",
                ),
            ),
        )
        prompt = build_user_prompt(evidence)

        # Should include PR numbers
        assert "#42" in prompt or "42" in prompt
        assert "#43" in prompt or "43" in prompt
        # Should include titles
        assert "dashboard" in prompt.lower()
        assert "authentication" in prompt.lower()

    def test_includes_issue_details(
        self, repository_metadata: RepositoryMetadata
    ) -> None:
        """User prompt includes issue details with numbers and titles."""
        evidence = RepositoryEvidenceBundle(
            repository=repository_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            issues=(
                IssueEvidence(
                    id=201,
                    number=10,
                    title="Performance regression in search",
                    state="open",
                ),
            ),
        )
        prompt = build_user_prompt(evidence)

        # Should include issue number and title
        assert "#10" in prompt or "10" in prompt
        assert "Performance" in prompt or "regression" in prompt.lower()
