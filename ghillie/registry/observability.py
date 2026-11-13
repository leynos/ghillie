"""Structured events for registry synchronization.

A sync emits one line per outcome-changing fact: how the run ended, each
cross-estate conflict it reported, and each ingestion toggle it changed. The
lines carry counts and identifiers rather than repository lists, so an estate
with many repositories cannot flood the log, and they never include SQL or
driver detail: a failure reports the same sanitised reason the raised
``RegistrySyncError`` carries.

Example:
-------
Follow one estate's syncs in the log::

    [SYNC_COMPLETED] estate_key=default dry_run=false duration_seconds=0.412
    outcome=success repositories_created=1 repositories_updated=0 ...

"""

from __future__ import annotations

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


def log_sync_conflict(estate_key: str, slug: str) -> None:
    """Log that this estate's catalogue names a repository another estate owns.

    Parameters
    ----------
    estate_key:
        The estate whose sync reported the conflict.
    slug:
        The ``owner/name`` slug the catalogue names.

    """
    log_info(
        logger,
        "[%s] estate_key=%s slug=%s",
        SyncEventType.SYNC_CONFLICTED,
        estate_key,
        slug,
    )


def log_ingestion_transition(
    estate_key: str,
    slug: str,
    *,
    transition: IngestionTransition,
    enabled: bool,
) -> None:
    """Log that a sync changed a repository's ingestion flag.

    Parameters
    ----------
    estate_key:
        The estate whose sync made the change.
    slug:
        The ``owner/name`` slug of the changed row.
    transition:
        The policy transition that produced the change.
    enabled:
        The ingestion flag the row now carries.

    """
    log_info(
        logger,
        "[%s] estate_key=%s slug=%s transition=%s enabled=%s",
        SyncEventType.INGESTION_TRANSITION,
        estate_key,
        slug,
        transition.value,
        _flag(value=enabled),
    )
