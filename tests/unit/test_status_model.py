"""Unit tests for status model interface and mock implementation."""

from __future__ import annotations

import asyncio
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
from ghillie.status import (
    MockStatusModel,
    RepositoryStatusResult,
    StatusModel,
    to_machine_summary,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
        generated_at=dt.datetime.now(dt.UTC),
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
        generated_at=dt.datetime.now(dt.UTC),
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
        issues=(
            IssueEvidence(
                id=202,
                number=11,
                title="Application crashes on startup",
                state="open",
                labels=("bug",),
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
        generated_at=dt.datetime.now(dt.UTC),
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


# ---------------------------------------------------------------------------
# RepositoryStatusResult struct tests
# ---------------------------------------------------------------------------


class TestRepositoryStatusResult:
    """Tests for RepositoryStatusResult struct."""

    def test_creation_with_required_fields(self) -> None:
        """RepositoryStatusResult can be created with required fields."""
        result = RepositoryStatusResult(
            summary="Repository is on track.",
            status=ReportStatus.ON_TRACK,
        )

        assert result.summary == "Repository is on track."
        assert result.status == ReportStatus.ON_TRACK
        assert result.highlights == ()
        assert result.risks == ()
        assert result.next_steps == ()

    def test_creation_with_all_fields(self) -> None:
        """RepositoryStatusResult can be created with all fields populated."""
        result = RepositoryStatusResult(
            summary="Repository is at risk due to pending issues.",
            status=ReportStatus.AT_RISK,
            highlights=("Delivered new API", "Improved test coverage"),
            risks=("Performance regression", "Missing documentation"),
            next_steps=("Address performance", "Update docs"),
        )

        assert result.summary == "Repository is at risk due to pending issues."
        assert result.status == ReportStatus.AT_RISK
        assert result.highlights == ("Delivered new API", "Improved test coverage")
        assert result.risks == ("Performance regression", "Missing documentation")
        assert result.next_steps == ("Address performance", "Update docs")

    def test_is_frozen(self) -> None:
        """RepositoryStatusResult is immutable."""
        result = RepositoryStatusResult(
            summary="Test",
            status=ReportStatus.ON_TRACK,
        )

        with pytest.raises(AttributeError):
            result.summary = "Modified"  # type: ignore[misc]

    def test_json_serialization_roundtrip(self) -> None:
        """RepositoryStatusResult can be serialized to and from JSON."""
        import msgspec

        original = RepositoryStatusResult(
            summary="Test summary",
            status=ReportStatus.AT_RISK,
            highlights=("Highlight 1",),
            risks=("Risk 1",),
            next_steps=("Step 1",),
        )

        encoded = msgspec.json.encode(original)
        decoded = msgspec.json.decode(encoded, type=RepositoryStatusResult)

        assert decoded.summary == original.summary
        assert decoded.status == original.status
        assert decoded.highlights == original.highlights
        assert decoded.risks == original.risks
        assert decoded.next_steps == original.next_steps


# ---------------------------------------------------------------------------
# to_machine_summary helper tests
# ---------------------------------------------------------------------------


class TestToMachineSummary:
    """Tests for to_machine_summary conversion helper."""

    def test_converts_to_dict_format(self) -> None:
        """to_machine_summary produces dict for Report.machine_summary."""
        result = RepositoryStatusResult(
            summary="Repository on track",
            status=ReportStatus.ON_TRACK,
            highlights=("Feature A", "Feature B"),
            risks=("Risk X",),
            next_steps=("Next 1", "Next 2"),
        )

        summary = to_machine_summary(result)

        assert summary["summary"] == "Repository on track"
        assert summary["status"] == "on_track"
        assert summary["highlights"] == ["Feature A", "Feature B"]
        assert summary["risks"] == ["Risk X"]
        assert summary["next_steps"] == ["Next 1", "Next 2"]

    def test_empty_collections_become_empty_lists(self) -> None:
        """Empty tuple collections become empty lists in dict."""
        result = RepositoryStatusResult(
            summary="Minimal",
            status=ReportStatus.UNKNOWN,
        )

        summary = to_machine_summary(result)

        assert summary["highlights"] == []
        assert summary["risks"] == []
        assert summary["next_steps"] == []


# ---------------------------------------------------------------------------
# StatusModel protocol tests
# ---------------------------------------------------------------------------


class TestStatusModelProtocol:
    """Tests for StatusModel protocol compliance."""

    def test_mock_implements_protocol(self) -> None:
        """MockStatusModel is recognized as implementing StatusModel."""
        model = MockStatusModel()
        assert isinstance(model, StatusModel)

    def test_protocol_is_runtime_checkable(self) -> None:
        """StatusModel protocol supports isinstance checks."""

        class NotAStatusModel:
            pass

        assert not isinstance(NotAStatusModel(), StatusModel)


# ---------------------------------------------------------------------------
# MockStatusModel heuristic tests
# ---------------------------------------------------------------------------


class TestMockStatusModelHeuristics:
    """Tests for MockStatusModel deterministic heuristics."""

    def test_returns_unknown_for_empty_evidence(
        self,
        empty_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock returns UNKNOWN when evidence bundle has no events."""
        model = MockStatusModel()
        result = asyncio.run(model.summarize_repository(empty_evidence))

        assert result.status == ReportStatus.UNKNOWN

    def test_returns_on_track_for_feature_activity(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock returns ON_TRACK for normal feature activity."""
        model = MockStatusModel()
        result = asyncio.run(model.summarize_repository(feature_evidence))

        assert result.status == ReportStatus.ON_TRACK

    def test_returns_at_risk_when_bugs_exceed_features(
        self,
        bug_heavy_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock returns AT_RISK when bug activity exceeds features."""
        model = MockStatusModel()
        result = asyncio.run(model.summarize_repository(bug_heavy_evidence))

        assert result.status == ReportStatus.AT_RISK

    def test_returns_at_risk_when_previous_risks_exist(
        self,
        evidence_with_previous_risks: RepositoryEvidenceBundle,
    ) -> None:
        """Mock returns AT_RISK when previous report had risks and AT_RISK status."""
        model = MockStatusModel()
        result = asyncio.run(model.summarize_repository(evidence_with_previous_risks))

        assert result.status == ReportStatus.AT_RISK


# ---------------------------------------------------------------------------
# MockStatusModel output quality tests
# ---------------------------------------------------------------------------


class TestMockStatusModelOutput:
    """Tests for MockStatusModel output content quality."""

    def test_summary_mentions_repository(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock generates summary mentioning repository slug."""
        model = MockStatusModel()
        result = asyncio.run(model.summarize_repository(feature_evidence))

        assert "octo/reef" in result.summary

    def test_summary_includes_event_counts(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock generates summary with event counts."""
        model = MockStatusModel()
        result = asyncio.run(model.summarize_repository(feature_evidence))

        # Evidence has 2 commits, 1 PR, 1 issue
        assert "2 commits" in result.summary
        assert "1 pull request" in result.summary
        assert "1 issue" in result.summary

    def test_summary_indicates_no_activity_when_empty(
        self,
        empty_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock generates appropriate summary for empty evidence."""
        model = MockStatusModel()
        result = asyncio.run(model.summarize_repository(empty_evidence))

        assert "no recorded activity" in result.summary.lower()

    def test_extracts_highlights_from_features(
        self,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Mock extracts highlights from feature work."""
        model = MockStatusModel()
        result = asyncio.run(model.summarize_repository(feature_evidence))

        # Should have highlight about delivered PRs
        assert len(result.highlights) > 0

    def test_carries_forward_previous_risks(
        self,
        evidence_with_previous_risks: RepositoryEvidenceBundle,
    ) -> None:
        """Mock carries forward risks from previous reports."""
        model = MockStatusModel()
        result = asyncio.run(model.summarize_repository(evidence_with_previous_risks))

        # Should reference ongoing risks
        assert len(result.risks) > 0
        # At least one risk should be marked as ongoing
        ongoing_risks = [r for r in result.risks if "ongoing" in r.lower()]
        assert len(ongoing_risks) > 0
