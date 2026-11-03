"""Pure ingestion-toggle policy for catalogue-to-Silver synchronisation.

The policy separates the *decision* about a repository's ``ingestion_enabled``
flag from the persistence work in :mod:`ghillie.registry.sync`. Keeping the
decision pure makes every transition exhaustively testable and gives operators
one place to read the rules:

* a new or unlinked row being adopted takes the catalogue's ``is_active`` flag;
* a linked row owned by the estate keeps its operator-set state unless the
  catalogue marks it inactive;
* a row owned by another estate is never touched and is reported as a conflict;
* a linked row removed from the catalogue is disabled, never re-enabled.

The module deliberately imports only the standard library so Hecate can hold it
in the ``domain_ports`` group.
"""

from __future__ import annotations

import dataclasses
import enum


class IngestionTransition(enum.StrEnum):
    """Named outcome of one ingestion decision.

    The enum doubles as the vocabulary for operator-facing diagnostics: a sync
    reports which transitions it applied so an operator can explain why a
    repository's state changed or did not change.
    """

    ADOPT = "adopt"
    PRESERVE = "preserve"
    DISABLE_INACTIVE = "disable_inactive"
    DISABLE_REMOVED = "disable_removed"
    CONFLICT = "conflict"


@dataclasses.dataclass(frozen=True, slots=True)
class SilverIngestionState:
    """The parts of a Silver row that the policy needs.

    Attributes
    ----------
    is_linked:
        True when the row carries a ``catalogue_repository_id``.
    is_owned_by_estate:
        True when the row's ``estate_id`` is this estate's id or is NULL (an
        unowned ad hoc row is adoptable).
    ingestion_enabled:
        The row's current ingestion flag.

    """

    is_linked: bool
    is_owned_by_estate: bool
    ingestion_enabled: bool


@dataclasses.dataclass(frozen=True, slots=True)
class IngestionDecision:
    """The desired ingestion flag together with the transition that produced it."""

    ingestion_enabled: bool
    transition: IngestionTransition


def decide_for_catalogue_repository(
    current: SilverIngestionState | None, *, catalogue_active: bool
) -> IngestionDecision:
    """Decide the ingestion flag for a repository present in the catalogue.

    Parameters
    ----------
    current:
        The existing Silver row state, or ``None`` when no row exists.
    catalogue_active:
        The catalogue repository's ``is_active`` flag.

    Returns
    -------
    IngestionDecision
        The transition applied and the resulting ``ingestion_enabled`` value.

    """
    if current is None:
        return IngestionDecision(
            ingestion_enabled=catalogue_active,
            transition=IngestionTransition.ADOPT,
        )
    if not current.is_owned_by_estate:
        return IngestionDecision(
            ingestion_enabled=current.ingestion_enabled,
            transition=IngestionTransition.CONFLICT,
        )
    if not current.is_linked:
        # An ad hoc row is adopted by the catalogue entry that now names it.
        return IngestionDecision(
            ingestion_enabled=catalogue_active,
            transition=IngestionTransition.ADOPT,
        )
    if not catalogue_active:
        return IngestionDecision(
            ingestion_enabled=False,
            transition=IngestionTransition.DISABLE_INACTIVE,
        )
    return IngestionDecision(
        ingestion_enabled=current.ingestion_enabled,
        transition=IngestionTransition.PRESERVE,
    )


def decide_for_removed_repository(
    current: SilverIngestionState,
) -> IngestionDecision:
    """Decide the ingestion flag for a row absent from this estate's catalogue.

    Parameters
    ----------
    current:
        The existing Silver row state.

    Returns
    -------
    IngestionDecision
        The transition applied and the resulting ``ingestion_enabled`` value.

    """
    if not current.is_owned_by_estate:
        return IngestionDecision(
            ingestion_enabled=current.ingestion_enabled,
            transition=IngestionTransition.CONFLICT,
        )
    if not current.is_linked:
        # An unlinked row never came from the catalogue, so its absence from
        # the catalogue says nothing about it.
        return IngestionDecision(
            ingestion_enabled=current.ingestion_enabled,
            transition=IngestionTransition.PRESERVE,
        )
    return IngestionDecision(
        ingestion_enabled=False,
        transition=IngestionTransition.DISABLE_REMOVED,
    )
