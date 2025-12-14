"""GitHub ingestion client and worker primitives."""

from __future__ import annotations

from .client import GitHubActivityClient, GitHubGraphQLClient, GitHubGraphQLConfig
from .ingestion import (
    GitHubIngestionConfig,
    GitHubIngestionResult,
    GitHubIngestionWorker,
)

__all__ = [
    "GitHubActivityClient",
    "GitHubGraphQLClient",
    "GitHubGraphQLConfig",
    "GitHubIngestionConfig",
    "GitHubIngestionResult",
    "GitHubIngestionWorker",
]
