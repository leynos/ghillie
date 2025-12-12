"""Data transfer objects for the repository registry."""

from __future__ import annotations

import dataclasses

from ghillie.common.slug import repo_slug


@dataclasses.dataclass(slots=True, frozen=True)
class RepositoryInfo:
    """Lightweight DTO for repository metadata needed by consumers.

    This immutable structure carries the essential repository attributes
    required by the ingestion worker and other downstream services.
    """

    id: str
    owner: str
    name: str
    default_branch: str
    ingestion_enabled: bool
    documentation_paths: tuple[str, ...]
    estate_id: str | None

    @property
    def slug(self) -> str:
        """Return owner/name to match catalogue notation."""
        return repo_slug(self.owner, self.name)


@dataclasses.dataclass(slots=True)
class SyncResult:
    """Summary of a catalogue-to-Silver synchronisation run.

    Tracks the number of repositories created, updated, or deactivated
    during a sync operation, enabling operators to monitor sync health.
    """

    estate_key: str
    repositories_created: int = 0
    repositories_updated: int = 0
    repositories_deactivated: int = 0
