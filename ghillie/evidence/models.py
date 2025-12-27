"""Evidence bundle structures for repository status reporting."""

from __future__ import annotations

import datetime as dt  # noqa: TC003
import enum

import msgspec


class WorkType(enum.StrEnum):
    """Classification of work items by type."""

    FEATURE = "feature"
    BUG = "bug"
    REFACTOR = "refactor"
    CHORE = "chore"
    DOCUMENTATION = "documentation"
    UNKNOWN = "unknown"


class ReportStatus(enum.StrEnum):
    """High-level status from a previous report."""

    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class RepositoryMetadata(msgspec.Struct, kw_only=True, frozen=True):
    """Basic repository identification and configuration.

    Attributes
    ----------
    id
        Internal repository UUID.
    owner
        GitHub organisation or owner name.
    name
        GitHub repository name.
    default_branch
        Default branch used for ingestion (e.g., "main").
    estate_id
        Optional estate identifier.
    documentation_paths
        Configured documentation locations to track.

    """

    id: str
    owner: str
    name: str
    default_branch: str
    estate_id: str | None = None
    documentation_paths: tuple[str, ...] = ()

    @property
    def slug(self) -> str:
        """Return owner/name identifier."""
        return f"{self.owner}/{self.name}"


class PreviousReportSummary(msgspec.Struct, kw_only=True, frozen=True):
    """Summary of a previous report for context.

    Attributes
    ----------
    report_id
        Unique report identifier.
    window_start
        Start of the reporting window.
    window_end
        End of the reporting window.
    status
        High-level status from the report.
    highlights
        Key highlights from the report.
    risks
        Identified risks from the report.
    event_count
        Number of events covered by the report.

    """

    report_id: str
    window_start: dt.datetime
    window_end: dt.datetime
    status: ReportStatus
    highlights: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    event_count: int = 0


class CommitEvidence(msgspec.Struct, kw_only=True, frozen=True):
    """Commit activity evidence for the reporting window.

    Attributes
    ----------
    sha
        Commit SHA.
    message
        Commit message (may be truncated for large messages).
    author_name
        Commit author name.
    author_email
        Commit author email.
    committed_at
        Commit timestamp.
    work_type
        Classified work type based on message/labels.
    is_merge_commit
        Whether this appears to be a merge commit.

    """

    sha: str
    message: str | None = None
    author_name: str | None = None
    author_email: str | None = None
    committed_at: dt.datetime | None = None
    work_type: WorkType = WorkType.UNKNOWN
    is_merge_commit: bool = False


class PullRequestEvidence(msgspec.Struct, kw_only=True, frozen=True):
    """Pull request evidence for the reporting window.

    Attributes
    ----------
    id
        GitHub PR ID.
    number
        PR number within the repository.
    title
        PR title.
    author_login
        PR author's GitHub login.
    state
        Current state (open, closed, merged).
    labels
        Applied labels.
    created_at
        When the PR was created.
    merged_at
        When the PR was merged (if merged).
    closed_at
        When the PR was closed (if closed).
    work_type
        Classified work type based on title/labels.
    is_draft
        Whether this is a draft PR.

    """

    id: int
    number: int
    title: str
    author_login: str | None = None
    state: str = "open"
    labels: tuple[str, ...] = ()
    created_at: dt.datetime | None = None
    merged_at: dt.datetime | None = None
    closed_at: dt.datetime | None = None
    work_type: WorkType = WorkType.UNKNOWN
    is_draft: bool = False


class IssueEvidence(msgspec.Struct, kw_only=True, frozen=True):
    """Issue evidence for the reporting window.

    Attributes
    ----------
    id
        GitHub issue ID.
    number
        Issue number within the repository.
    title
        Issue title.
    author_login
        Issue author's GitHub login.
    state
        Current state (open, closed).
    labels
        Applied labels.
    created_at
        When the issue was created.
    closed_at
        When the issue was closed (if closed).
    work_type
        Classified work type based on title/labels.

    """

    id: int
    number: int
    title: str
    author_login: str | None = None
    state: str = "open"
    labels: tuple[str, ...] = ()
    created_at: dt.datetime | None = None
    closed_at: dt.datetime | None = None
    work_type: WorkType = WorkType.UNKNOWN


class DocumentationEvidence(msgspec.Struct, kw_only=True, frozen=True):
    """Documentation change evidence.

    Attributes
    ----------
    path
        File path within the repository.
    change_type
        Type of change (added, modified, deleted).
    commit_sha
        Associated commit SHA.
    occurred_at
        When the change occurred.
    is_roadmap
        Whether this is a roadmap document.
    is_adr
        Whether this is an ADR document.

    """

    path: str
    change_type: str
    commit_sha: str
    occurred_at: dt.datetime
    is_roadmap: bool = False
    is_adr: bool = False


class WorkTypeGrouping(msgspec.Struct, kw_only=True, frozen=True):
    """Events grouped by work type for summary generation.

    Attributes
    ----------
    work_type
        The work type for this grouping.
    commit_count
        Number of commits in this category.
    pr_count
        Number of pull requests in this category.
    issue_count
        Number of issues in this category.
    sample_titles
        Representative titles (max 5) for the category.

    """

    work_type: WorkType
    commit_count: int = 0
    pr_count: int = 0
    issue_count: int = 0
    sample_titles: tuple[str, ...] = ()


class RepositoryEvidenceBundle(msgspec.Struct, kw_only=True, frozen=True):
    """Complete evidence bundle for a repository reporting window.

    This structure aggregates all evidence needed to generate a repository
    status report, including metadata, historical context, and new activity.

    Attributes
    ----------
    repository
        Repository identification and configuration.
    window_start
        Start of the reporting window (inclusive).
    window_end
        End of the reporting window (exclusive).
    previous_reports
        Previous one or two reports for context (most recent first).
    commits
        New commits within the window.
    pull_requests
        Pull requests active within the window.
    issues
        Issues created or closed within the window.
    documentation_changes
        Documentation changes within the window.
    work_type_groupings
        Events grouped by work type.
    event_fact_ids
        IDs of EventFact records covered by this bundle.
    generated_at
        When this bundle was generated.

    """

    repository: RepositoryMetadata
    window_start: dt.datetime
    window_end: dt.datetime
    previous_reports: tuple[PreviousReportSummary, ...] = ()
    commits: tuple[CommitEvidence, ...] = ()
    pull_requests: tuple[PullRequestEvidence, ...] = ()
    issues: tuple[IssueEvidence, ...] = ()
    documentation_changes: tuple[DocumentationEvidence, ...] = ()
    work_type_groupings: tuple[WorkTypeGrouping, ...] = ()
    event_fact_ids: tuple[int, ...] = ()
    generated_at: dt.datetime | None = None

    @property
    def total_event_count(self) -> int:
        """Return total number of events in the bundle."""
        return (
            len(self.commits)
            + len(self.pull_requests)
            + len(self.issues)
            + len(self.documentation_changes)
        )

    @property
    def has_previous_context(self) -> bool:
        """Return True if previous reports are available for context."""
        return len(self.previous_reports) > 0
