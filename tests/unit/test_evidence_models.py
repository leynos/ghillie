"""Unit tests for evidence bundle model structures."""

from __future__ import annotations

import datetime as dt
import typing as typ

import msgspec
import pytest

from ghillie.evidence import (
    CommitEvidence,
    DocumentationEvidence,
    IssueEvidence,
    PreviousReportSummary,
    PullRequestEvidence,
    ReportStatus,
    RepositoryEvidenceBundle,
    RepositoryMetadata,
    WorkType,
    WorkTypeGrouping,
)


class TestWorkTypeEnum:
    """Tests for WorkType enum."""

    def test_work_type_values(self) -> None:
        assert WorkType.FEATURE == "feature"
        assert WorkType.BUG == "bug"
        assert WorkType.REFACTOR == "refactor"
        assert WorkType.CHORE == "chore"
        assert WorkType.DOCUMENTATION == "documentation"
        assert WorkType.UNKNOWN == "unknown"

    def test_work_type_is_str_enum(self) -> None:
        assert str(WorkType.FEATURE) == "feature"
        assert f"type: {WorkType.BUG}" == "type: bug"


class TestReportStatusEnum:
    """Tests for ReportStatus enum."""

    def test_report_status_values(self) -> None:
        assert ReportStatus.ON_TRACK == "on_track"
        assert ReportStatus.AT_RISK == "at_risk"
        assert ReportStatus.BLOCKED == "blocked"
        assert ReportStatus.UNKNOWN == "unknown"


class TestRepositoryMetadata:
    """Tests for RepositoryMetadata struct."""

    def test_slug_property(self) -> None:
        metadata = RepositoryMetadata(
            id="abc-123",
            owner="octo",
            name="reef",
            default_branch="main",
        )

        assert metadata.slug == "octo/reef"

    def test_default_values(self) -> None:
        metadata = RepositoryMetadata(
            id="abc-123",
            owner="octo",
            name="reef",
            default_branch="main",
        )

        assert metadata.estate_id is None
        assert metadata.documentation_paths == ()

    def test_frozen_immutability(self) -> None:
        metadata = RepositoryMetadata(
            id="abc-123",
            owner="octo",
            name="reef",
            default_branch="main",
        )
        mutable_metadata = typ.cast("typ.Any", metadata)

        with pytest.raises(AttributeError):
            mutable_metadata.owner = "other"

    def test_msgspec_encoding_roundtrip(self) -> None:
        metadata = RepositoryMetadata(
            id="abc-123",
            owner="octo",
            name="reef",
            default_branch="main",
            estate_id="estate-1",
            documentation_paths=("docs/roadmap.md", "docs/adr/"),
        )

        encoded = msgspec.json.encode(metadata)
        decoded = msgspec.json.decode(encoded, type=RepositoryMetadata)

        assert decoded.id == "abc-123"
        assert decoded.slug == "octo/reef"
        assert decoded.documentation_paths == ("docs/roadmap.md", "docs/adr/")


class TestCommitEvidence:
    """Tests for CommitEvidence struct."""

    def test_default_values(self) -> None:
        commit = CommitEvidence(sha="abc123")

        assert commit.message is None
        assert commit.author_name is None
        assert commit.author_email is None
        assert commit.committed_at is None
        assert commit.work_type == WorkType.UNKNOWN
        assert commit.is_merge_commit is False

    def test_full_construction(self) -> None:
        committed_at = dt.datetime(2024, 7, 15, 10, 30, tzinfo=dt.UTC)
        commit = CommitEvidence(
            sha="abc123def456",
            message="feat: add new feature",
            author_name="Alice",
            author_email="alice@example.com",
            committed_at=committed_at,
            work_type=WorkType.FEATURE,
            is_merge_commit=False,
        )

        assert commit.sha == "abc123def456"
        assert commit.message == "feat: add new feature"
        assert commit.work_type == WorkType.FEATURE

    def test_frozen_immutability(self) -> None:
        commit = CommitEvidence(sha="abc123")
        mutable_commit = typ.cast("typ.Any", commit)

        with pytest.raises(AttributeError):
            mutable_commit.sha = "other"


class TestPullRequestEvidence:
    """Tests for PullRequestEvidence struct."""

    def test_default_values(self) -> None:
        pr = PullRequestEvidence(id=123, number=45, title="Add feature")

        assert pr.author_login is None
        assert pr.state == "open"
        assert pr.labels == ()
        assert pr.created_at is None
        assert pr.merged_at is None
        assert pr.closed_at is None
        assert pr.work_type == WorkType.UNKNOWN
        assert pr.is_draft is False

    def test_full_construction(self) -> None:
        created_at = dt.datetime(2024, 7, 10, tzinfo=dt.UTC)
        merged_at = dt.datetime(2024, 7, 15, tzinfo=dt.UTC)

        pr = PullRequestEvidence(
            id=123,
            number=45,
            title="fix: resolve login issue",
            author_login="bob",
            state="merged",
            labels=("bug", "priority:high"),
            created_at=created_at,
            merged_at=merged_at,
            work_type=WorkType.BUG,
            is_draft=False,
        )

        assert pr.labels == ("bug", "priority:high")
        assert pr.work_type == WorkType.BUG


class TestIssueEvidence:
    """Tests for IssueEvidence struct."""

    def test_default_values(self) -> None:
        issue = IssueEvidence(id=789, number=12, title="Bug report")

        assert issue.author_login is None
        assert issue.state == "open"
        assert issue.labels == ()
        assert issue.work_type == WorkType.UNKNOWN

    def test_full_construction(self) -> None:
        issue = IssueEvidence(
            id=789,
            number=12,
            title="Feature request: dark mode",
            author_login="charlie",
            state="open",
            labels=("enhancement", "ui"),
            created_at=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            work_type=WorkType.FEATURE,
        )

        assert issue.labels == ("enhancement", "ui")
        assert issue.work_type == WorkType.FEATURE


class TestDocumentationEvidence:
    """Tests for DocumentationEvidence struct."""

    def test_default_flags(self) -> None:
        doc = DocumentationEvidence(
            path="README.md",
            change_type="modified",
            commit_sha="abc123",
            occurred_at=dt.datetime(2024, 7, 15, tzinfo=dt.UTC),
        )

        assert doc.is_roadmap is False
        assert doc.is_adr is False

    def test_roadmap_flag(self) -> None:
        doc = DocumentationEvidence(
            path="docs/roadmap.md",
            change_type="added",
            commit_sha="abc123",
            occurred_at=dt.datetime(2024, 7, 15, tzinfo=dt.UTC),
            is_roadmap=True,
        )

        assert doc.is_roadmap is True


class TestPreviousReportSummary:
    """Tests for PreviousReportSummary struct."""

    def test_default_values(self) -> None:
        summary = PreviousReportSummary(
            report_id="rpt-123",
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            status=ReportStatus.ON_TRACK,
        )

        assert summary.highlights == ()
        assert summary.risks == ()
        assert summary.event_count == 0

    def test_full_construction(self) -> None:
        summary = PreviousReportSummary(
            report_id="rpt-123",
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            status=ReportStatus.AT_RISK,
            highlights=("Shipped v2.0", "Resolved critical bug"),
            risks=("Tech debt increasing",),
            event_count=42,
        )

        assert summary.status == ReportStatus.AT_RISK
        assert len(summary.highlights) == 2
        assert summary.event_count == 42


class TestWorkTypeGrouping:
    """Tests for WorkTypeGrouping struct."""

    def test_default_values(self) -> None:
        grouping = WorkTypeGrouping(work_type=WorkType.FEATURE)

        assert grouping.commit_count == 0
        assert grouping.pr_count == 0
        assert grouping.issue_count == 0
        assert grouping.sample_titles == ()

    def test_full_construction(self) -> None:
        grouping = WorkTypeGrouping(
            work_type=WorkType.BUG,
            commit_count=5,
            pr_count=2,
            issue_count=3,
            sample_titles=("Fix login", "Resolve crash", "Handle null"),
        )

        assert grouping.work_type == WorkType.BUG
        assert grouping.commit_count == 5
        assert len(grouping.sample_titles) == 3


class TestRepositoryEvidenceBundle:
    """Tests for RepositoryEvidenceBundle struct."""

    @pytest.fixture
    def sample_metadata(self) -> RepositoryMetadata:
        return RepositoryMetadata(
            id="abc-123",
            owner="octo",
            name="reef",
            default_branch="main",
        )

    def test_minimal_construction(self, sample_metadata: RepositoryMetadata) -> None:
        bundle = RepositoryEvidenceBundle(
            repository=sample_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        )

        assert bundle.repository.slug == "octo/reef"
        assert bundle.commits == ()
        assert bundle.pull_requests == ()
        assert bundle.issues == ()
        assert bundle.documentation_changes == ()

    def test_total_event_count_property(
        self, sample_metadata: RepositoryMetadata
    ) -> None:
        bundle = RepositoryEvidenceBundle(
            repository=sample_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            commits=(CommitEvidence(sha="a"), CommitEvidence(sha="b")),
            pull_requests=(PullRequestEvidence(id=1, number=1, title="PR1"),),
            issues=(
                IssueEvidence(id=1, number=1, title="Issue1"),
                IssueEvidence(id=2, number=2, title="Issue2"),
            ),
            documentation_changes=(
                DocumentationEvidence(
                    path="README.md",
                    change_type="modified",
                    commit_sha="a",
                    occurred_at=dt.datetime(2024, 7, 5, tzinfo=dt.UTC),
                ),
            ),
        )

        assert bundle.total_event_count == 6

    def test_has_previous_context_false(
        self, sample_metadata: RepositoryMetadata
    ) -> None:
        bundle = RepositoryEvidenceBundle(
            repository=sample_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        )

        assert bundle.has_previous_context is False

    def test_has_previous_context_true(
        self, sample_metadata: RepositoryMetadata
    ) -> None:
        previous = PreviousReportSummary(
            report_id="rpt-1",
            window_start=dt.datetime(2024, 6, 24, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            status=ReportStatus.ON_TRACK,
        )

        bundle = RepositoryEvidenceBundle(
            repository=sample_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            previous_reports=(previous,),
        )

        assert bundle.has_previous_context is True

    def test_frozen_immutability(self, sample_metadata: RepositoryMetadata) -> None:
        bundle = RepositoryEvidenceBundle(
            repository=sample_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        )
        mutable_bundle = typ.cast("typ.Any", bundle)

        with pytest.raises(AttributeError):
            mutable_bundle.commits = ()

    def test_msgspec_encoding_roundtrip(
        self, sample_metadata: RepositoryMetadata
    ) -> None:
        bundle = RepositoryEvidenceBundle(
            repository=sample_metadata,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
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
                    sample_titles=("feat: add feature",),
                ),
            ),
            generated_at=dt.datetime(2024, 7, 8, 12, 0, tzinfo=dt.UTC),
        )

        encoded = msgspec.json.encode(bundle)
        decoded = msgspec.json.decode(encoded, type=RepositoryEvidenceBundle)

        assert decoded.repository.slug == "octo/reef"
        assert decoded.total_event_count == 1
        assert decoded.commits[0].work_type == WorkType.FEATURE
        assert decoded.work_type_groupings[0].commit_count == 1
