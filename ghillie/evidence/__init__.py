"""Evidence bundle generation for repository status reporting."""

from __future__ import annotations

from .classification import (
    DEFAULT_CLASSIFICATION_CONFIG,
    ClassificationConfig,
    classify_by_labels,
    classify_by_title,
    classify_commit,
    classify_issue,
    classify_pull_request,
    is_merge_commit,
)
from .models import (
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
from .service import EvidenceBundleService

__all__ = [
    "DEFAULT_CLASSIFICATION_CONFIG",
    "ClassificationConfig",
    "CommitEvidence",
    "DocumentationEvidence",
    "EvidenceBundleService",
    "IssueEvidence",
    "PreviousReportSummary",
    "PullRequestEvidence",
    "ReportStatus",
    "RepositoryEvidenceBundle",
    "RepositoryMetadata",
    "WorkType",
    "WorkTypeGrouping",
    "classify_by_labels",
    "classify_by_title",
    "classify_commit",
    "classify_issue",
    "classify_pull_request",
    "is_merge_commit",
]
