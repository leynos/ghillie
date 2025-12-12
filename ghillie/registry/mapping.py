"""Mapping helpers for registry DTOs."""

from __future__ import annotations

import typing as typ

from ghillie.registry.models import RepositoryInfo

if typ.TYPE_CHECKING:
    from ghillie.silver.storage import Repository


def to_repository_info(repo: Repository) -> RepositoryInfo:
    """Convert a Silver Repository to a RepositoryInfo DTO."""
    return RepositoryInfo(
        id=repo.id,
        owner=repo.github_owner,
        name=repo.github_name,
        default_branch=repo.default_branch,
        ingestion_enabled=repo.ingestion_enabled,
        documentation_paths=tuple(repo.documentation_paths),
        estate_id=repo.estate_id,
    )
