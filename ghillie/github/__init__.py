"""GitHub ingestion client and worker primitives."""

from __future__ import annotations

from .client import GitHubActivityClient, GitHubGraphQLClient, GitHubGraphQLConfig
from .ingestion import (
    GitHubIngestionConfig,
    GitHubIngestionResult,
    GitHubIngestionWorker,
)
from .lag import IngestionHealthConfig, IngestionHealthService, IngestionLagMetrics
from .observability import (
    ErrorCategory,
    IngestionEventLogger,
    IngestionEventType,
    IngestionRunContext,
    categorize_error,
)

__all__ = [
    "ErrorCategory",
    "GitHubActivityClient",
    "GitHubGraphQLClient",
    "GitHubGraphQLConfig",
    "GitHubIngestionConfig",
    "GitHubIngestionResult",
    "GitHubIngestionWorker",
    "IngestionEventLogger",
    "IngestionEventType",
    "IngestionHealthConfig",
    "IngestionHealthService",
    "IngestionLagMetrics",
    "IngestionRunContext",
    "categorize_error",
]
