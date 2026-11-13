"""Structured events for registry synchronization.

A sync emits one terminal line per run, one line per cross-estate conflict it
reported, and one line per ingestion toggle it changed. The terminal lines
carry counts rather than repository lists, so they stay one line whatever the
estate's size; the per-slug lines scale with the conflicts and changes the run
actually made, not with the estate. No line includes SQL or driver detail: a
failure reports the same sanitized reason the raised ``RegistrySyncError``
carries.

The per-slug lines are recorded while the run's transaction is still open and
published only once it settles, so a line never describes a change that was
rolled back. A dry run publishes after its rollback with ``dry_run=true``.

Example:
-------
Follow one estate's syncs in the log::

    [SYNC_COMPLETED] estate_key=default dry_run=false duration_seconds=0.412
    outcome=success repositories_created=1 repositories_updated=0 ...

"""

from __future__ import annotations

import dataclasses
import enum
import typing as typ

from ghillie.logging import get_logger, log_error, log_info

if typ.TYPE_CHECKING:
    from ghillie.registry.models import SyncResult
    from ghillie.registry.policy import IngestionTransition

logger = get_logger(__name__)


class SyncEventType(enum.StrEnum):
    """The events a registry sync emits."""

    SYNC_COMPLETED = "SYNC_COMPLETED"
    SYNC_FAILED = "SYNC_FAILED"
    SYNC_CONFLICTED = "SYNC_CONFLICTED"
    INGESTION_TRANSITION = "INGESTION_TRANSITION"


def _flag(*, value: bool) -> str:
    """Render a boolean the way the event vocabulary spells it."""
    return "true" if value else "false"


def log_sync_completed(
    result: SyncResult,
    *,
    dry_run: bool,
    duration_seconds: float,
) -> None:
    """Log that a sync run finished, with the counts it produced.

    Parameters
    ----------
    result:
        The run's summary. Its estate key names the run and its counts are the
        aggregate outcome.
    dry_run:
        Whether the run rolled its work back instead of committing it.
    duration_seconds:
        Wall-clock duration of the run, in seconds.

    """
    log_info(
        logger,
        "[%s] estate_key=%s dry_run=%s duration_seconds=%.3f outcome=success "
        "repositories_created=%d repositories_updated=%d "
        "repositories_deactivated=%d repositories_conflicted=%d "
        "repositories_left_disabled=%d",
        SyncEventType.SYNC_COMPLETED,
        result.estate_key,
        _flag(value=dry_run),
        duration_seconds,
        result.repositories_created,
        result.repositories_updated,
        result.repositories_deactivated,
        len(result.repositories_conflicted),
        result.repositories_left_disabled_count,
    )


def log_sync_failed(
    estate_key: str,
    *,
    dry_run: bool,
    duration_seconds: float,
    reason: str,
) -> None:
    """Log that a sync run failed, with the sanitised reason it raised.

    Parameters
    ----------
    estate_key:
        The estate the failed run projected.
    dry_run:
        Whether the run was a dry run.
    duration_seconds:
        Wall-clock duration until the failure, in seconds.
    reason:
        The ``RegistrySyncError`` reason. It never carries SQL or driver
        detail, so it is safe to log as-is.

    """
    log_error(
        logger,
        "[%s] estate_key=%s dry_run=%s duration_seconds=%.3f outcome=failure reason=%s",
        SyncEventType.SYNC_FAILED,
        estate_key,
        _flag(value=dry_run),
        duration_seconds,
        reason,
    )


def log_sync_conflict(estate_key: str, slug: str, *, dry_run: bool) -> None:
    """Log that this estate's catalogue names a repository another estate owns.

    Parameters
    ----------
    estate_key:
        The estate whose sync reported the conflict.
    slug:
        The ``owner/name`` slug the catalogue names.
    dry_run:
        Whether the reporting run rolls its work back instead of committing it.

    """
    log_info(
        logger,
        "[%s] estate_key=%s dry_run=%s slug=%s",
        SyncEventType.SYNC_CONFLICTED,
        estate_key,
        _flag(value=dry_run),
        slug,
    )


@dataclasses.dataclass(frozen=True, slots=True)
class PendingTransition:
    """One recorded ingestion-flag change, awaiting its transaction's fate."""

    slug: str
    transition: IngestionTransition
    enabled: bool


def log_ingestion_transition(
    estate_key: str,
    pending: PendingTransition,
    *,
    dry_run: bool,
) -> None:
    """Log that a sync changed a repository's ingestion flag.

    Parameters
    ----------
    estate_key:
        The estate whose sync made the change.
    pending:
        The recorded change: the ``owner/name`` slug, the policy transition
        that produced it, and the ingestion flag the row now carries.
    dry_run:
        Whether the change is one the run rolled back. A committed change
        carries ``false``; a preview's projected change carries ``true``.

    """
    log_info(
        logger,
        "[%s] estate_key=%s dry_run=%s slug=%s transition=%s enabled=%s",
        SyncEventType.INGESTION_TRANSITION,
        estate_key,
        _flag(value=dry_run),
        pending.slug,
        pending.transition.value,
        _flag(value=pending.enabled),
    )


@dataclasses.dataclass(slots=True)
class SyncEventBuffer:
    """The per-slug events a run has recorded but not yet published.

    A sync writes many rows in one transaction, so publishing a change as it
    happens would report work a later failure rolls back. The run records its
    conflicts and transitions here and publishes them only after the
    transaction settles: after a commit, or after a dry run's rollback with
    ``dry_run=True``. A failed run publishes nothing, because its failure
    event already says the work did not happen.
    """

    _conflicts: list[str] = dataclasses.field(default_factory=list)
    _transitions: list[PendingTransition] = dataclasses.field(default_factory=list)

    @property
    def conflicts(self) -> tuple[str, ...]:
        """The slugs recorded as conflicts, in the order they were seen."""
        return tuple(self._conflicts)

    @property
    def transitions(self) -> tuple[PendingTransition, ...]:
        """The ingestion changes recorded, in the order they were made."""
        return tuple(self._transitions)

    def record_conflict(self, slug: str) -> None:
        """Record that another estate owns this slug."""
        self._conflicts.append(slug)

    def record_transition(
        self,
        slug: str,
        *,
        transition: IngestionTransition,
        enabled: bool,
    ) -> None:
        """Record that the run changed this repository's ingestion flag."""
        self._transitions.append(
            PendingTransition(slug=slug, transition=transition, enabled=enabled)
        )

    def publish(self, estate_key: str, *, dry_run: bool) -> None:
        """Log every recorded event once the run's transaction has settled."""
        for slug in self._conflicts:
            log_sync_conflict(estate_key, slug, dry_run=dry_run)
        for pending in self._transitions:
            log_ingestion_transition(estate_key, pending, dry_run=dry_run)
