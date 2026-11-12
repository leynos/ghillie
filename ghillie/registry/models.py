"""Data transfer objects for the repository registry."""

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


LEFT_DISABLED_PREVIEW_LIMIT = 100
"""Maximum number of slugs echoed in ``SyncResult.repositories_left_disabled``.

The count is always exact; the list is a bounded preview so a large estate
cannot produce an unbounded response body.
"""


@dataclasses.dataclass(slots=True)
class SyncResult:
    """Summary of a catalogue-to-Silver synchronisation run.

    Tracks the number of repositories created, updated, or deactivated
    during a sync operation, enabling operators to monitor sync health.

    ``repositories_conflicted`` lists repositories that this estate's catalogue
    names but another estate owns; sync leaves them untouched. The
    ``repositories_left_disabled`` preview and its count report active
    catalogue repositories whose linked Silver row was disabled in the view
    this sync loaded and that the sync left disabled. They are an observation
    of that view plus this sync's own writes, not a re-read of committed
    state: a toggle another writer commits after the load is not seen, and the
    sync does not overwrite it. The exception is a lost adoption claim, which
    reloads that one row to judge ownership: a toggle committed before the
    reload can be seen, and a row it makes enabled is not reported as left
    disabled. They say that ingestion is off, not why: a row may have been
    disabled by an operator or by an earlier removal.
    ``repositories_deactivated`` counts only removed rows that this sync turned
    from enabled to disabled, so a removed row an operator had already
    disabled is not counted again.
    """

    estate_key: str
    repositories_created: int = 0
    repositories_updated: int = 0
    repositories_deactivated: int = 0
    repositories_conflicted: list[str] = dataclasses.field(default_factory=list)
    repositories_left_disabled: list[str] = dataclasses.field(default_factory=list)
    repositories_left_disabled_count: int = 0

    def note_left_disabled(self, slug: str) -> None:
        """Record a repository that sync left disabled, bounding the preview."""
        self.repositories_left_disabled_count += 1
        if len(self.repositories_left_disabled) < LEFT_DISABLED_PREVIEW_LIMIT:
            self.repositories_left_disabled.append(slug)
