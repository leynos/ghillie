"""Evidence bundle generation for repository status reporting."""

from __future__ import annotations

from .classification import (
    DEFAULT_CLASSIFICATION_CONFIG,
    Classifiable,
    ClassificationConfig,
    classify_by_labels,
    classify_by_title,
    classify_commit,
    classify_entity,
    is_merge_commit,
)
from .models import (
    CommitEvidence,
    ComponentDependencyEvidence,
    ComponentEvidence,
    ComponentRepositorySummary,
    DocumentationEvidence,
    IssueEvidence,
    PreviousReportSummary,
    ProjectEvidenceBundle,
    ProjectMetadata,
    PullRequestEvidence,
    ReportStatus,
    RepositoryEvidenceBundle,
    RepositoryMetadata,
    WorkType,
    WorkTypeGrouping,
)
from .project_service import ProjectEvidenceBundleService
from .service import EvidenceBundleService

__all__ = [
    "DEFAULT_CLASSIFICATION_CONFIG",
    "Classifiable",
    "ClassificationConfig",
    "CommitEvidence",
    "ComponentDependencyEvidence",
    "ComponentEvidence",
    "ComponentRepositorySummary",
    "DocumentationEvidence",
    "EvidenceBundleService",
    "IssueEvidence",
    "PreviousReportSummary",
    "ProjectEvidenceBundle",
    "ProjectEvidenceBundleService",
    "ProjectMetadata",
    "PullRequestEvidence",
    "ReportStatus",
    "RepositoryEvidenceBundle",
    "RepositoryMetadata",
    "WorkType",
    "WorkTypeGrouping",
    "classify_by_labels",
    "classify_by_title",
    "classify_commit",
    "classify_entity",
    "is_merge_commit",
]
