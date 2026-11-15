"""Structured records for estate mutations (D21).

Every mutation attempt emits exactly one terminal record, whatever its
outcome. The record names the operation, the estate or repository it touched,
the request's commit and dry-run flag, the work's counts, how long it took and
how it ended. :class:`MutationRecorder` owns that rendering and the clock, so
the application service decides only *which* outcome applies and stays about
orchestration.

Counts, never item lists, are rendered: a record stays one line whatever the
estate's size.

Example:
-------
Follow one estate's imports in the log::

    estate.import estate_key='default' commit_sha='9f2c1ab' dry_run=false
    projects=1/0/0 components=2/0/0 repositories=1/0/0 edges=1/0/0
    duration_ms=12.4 outcome=succeeded

"""

from __future__ import annotations

import dataclasses
import enum
import time
import typing as typ

from ghillie.logging import get_logger, log_info

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from ghillie.estate.models import CatalogueImportSummary, RegistrySyncSummary

logger = get_logger(__name__)


class MutationOutcome(enum.StrEnum):
    """The terminal outcomes a mutation attempt can record."""

    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"
    # Cancellation is terminal too, even though the caller sees an exception:
    # without a record of its own, a shutdown would look like a hang.
    CANCELLED = "cancelled"


@dataclasses.dataclass(frozen=True, slots=True)
class MutationRecord:
    """Request-scoped fields shared by every structured mutation line."""

    operation: str
    estate_key: str
    commit_sha: str | None
    dry_run: bool
    started: float


@dataclasses.dataclass(frozen=True, slots=True)
class ToggleRecord:
    """Request-scoped fields shared by every ingestion toggle record."""

    owner: str
    name: str
    enabled: bool
    started: float


class MutationRecorder:
    """Render and time the D21 records for one service instance.

    Parameters
    ----------
    clock:
        Monotonic clock returning seconds. The default is
        :func:`time.perf_counter`; a test substitutes its own to pin the
        rendered duration.

    Notes
    -----
    The recorder is injected rather than reached for through a module global,
    so a caller can supply a deterministic clock without patching time.

    """

    def __init__(
        self,
        *,
        clock: cabc.Callable[[], float] = time.perf_counter,
    ) -> None:
        """Store the clock used to time each attempt."""
        self._clock = clock

    def begin_mutation(
        self,
        *,
        operation: str,
        estate_key: str,
        commit_sha: str | None,
        dry_run: bool,
    ) -> MutationRecord:
        """Start timing one mutation attempt.

        Parameters
        ----------
        operation:
            Log name of the mutation, such as ``estate.import``.
        estate_key:
            Key of the estate being mutated.
        commit_sha:
            Commit the request names, or ``None`` for a mutation that has no
            commit.
        dry_run:
            Whether the request asked for its work to be rolled back.

        Returns
        -------
        MutationRecord
            A record whose duration is measured from this call.

        """
        return MutationRecord(
            operation=operation,
            estate_key=estate_key,
            commit_sha=commit_sha,
            dry_run=dry_run,
            started=self._clock(),
        )

    def begin_toggle(self, *, owner: str, name: str, enabled: bool) -> ToggleRecord:
        """Start timing one ingestion toggle.

        Parameters
        ----------
        owner:
            Repository owner.
        name:
            Repository name.
        enabled:
            The state the request asked for.

        Returns
        -------
        ToggleRecord
            A record whose duration is measured from this call.

        """
        return ToggleRecord(
            owner=owner,
            name=name,
            enabled=enabled,
            started=self._clock(),
        )

    def record_mutation(
        self,
        record: MutationRecord,
        *,
        outcome: MutationOutcome,
        details: str,
    ) -> None:
        """Write the one structured mutation line required by D21.

        ``estate_key`` and ``commit_sha`` come from the request, so they are
        rendered with ``%r``: a newline or other control character must appear
        as an escape rather than split the record into a forged second line.

        Parameters
        ----------
        record:
            The attempt's request fields and start time.
        outcome:
            How the attempt ended. This line is the attempt's only record.
        details:
            Rendered counts for a completed attempt, or the failure summary
            for an attempt that did not complete.

        """
        log_info(
            logger,
            "%s estate_key=%r commit_sha=%r dry_run=%s %s duration_ms=%.1f outcome=%s",
            record.operation,
            record.estate_key,
            record.commit_sha or "-",
            record.dry_run,
            details,
            self._elapsed_ms(record.started),
            outcome,
        )

    def record_toggle(
        self,
        record: ToggleRecord,
        *,
        outcome: MutationOutcome,
        details: str,
    ) -> None:
        """Write the structured record for one ingestion toggle.

        The repository identity is rendered with ``%r`` for the same reason as
        the estate key: both come from the request and must not be able to
        forge a second record.

        Parameters
        ----------
        record:
            The toggle's request fields and start time.
        outcome:
            How the attempt ended.
        details:
            Rendered state change for a completed toggle, or the failure
            summary for an attempt that did not complete.

        """
        log_info(
            logger,
            "estate.set-ingestion owner=%r name=%r enabled=%s %s "
            "duration_ms=%.1f outcome=%s",
            record.owner,
            record.name,
            record.enabled,
            details,
            self._elapsed_ms(record.started),
            outcome,
        )

    def _elapsed_ms(self, started: float) -> float:
        """Return the milliseconds elapsed since *started*."""
        return (self._clock() - started) * 1000


def import_details(summary: CatalogueImportSummary) -> str:
    """Render the per-record counts for the structured import line."""
    return (
        f"projects={summary.projects.created}/"
        f"{summary.projects.updated}/{summary.projects.deleted} "
        f"components={summary.components.created}/"
        f"{summary.components.updated}/{summary.components.deleted} "
        f"repositories={summary.repositories.created}/"
        f"{summary.repositories.updated}/"
        f"{summary.repositories.deleted} "
        f"edges={summary.edges.created}/"
        f"{summary.edges.updated}/"
        f"{summary.edges.deleted}"
    )


def sync_details(summary: RegistrySyncSummary) -> str:
    """Render the per-repository counts for the structured sync line."""
    return (
        f"created={summary.repositories_created} "
        f"updated={summary.repositories_updated} "
        f"deactivated={summary.repositories_deactivated} "
        f"conflicted={len(summary.repositories_conflicted)} "
        f"left_disabled={summary.repositories_left_disabled_count}"
    )


def failure_details(exc: BaseException) -> str:
    """Render the failure class and message for the structured mutation line.

    The message can quote client-supplied text, so it is rendered with ``%r``
    for the same reason as the request fields: a newline must not be able to
    forge a second record.

    Parameters
    ----------
    exc:
        The failure that ended the attempt. It is only read, never raised, so
        cancellation (which derives from ``BaseException``) is accepted too.

    Returns
    -------
    str
        The failure's class name and quoted message.

    """
    return f"error={type(exc).__name__} message={str(exc)!r}"
