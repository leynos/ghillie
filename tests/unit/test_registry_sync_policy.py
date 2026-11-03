"""Exhaustive unit tests for the pure registry ingestion policy.

The input space is finite: a Silver row is either absent or has three booleans,
and a catalogue repository is either active or inactive. The two tables below
enumerate every combination so the test is a complete check rather than a
sample.
"""

from __future__ import annotations

import dataclasses
import itertools

import pytest

from ghillie.registry.policy import (
    IngestionDecision,
    IngestionTransition,
    SilverIngestionState,
    decide_for_catalogue_repository,
    decide_for_removed_repository,
)


def _state(*, linked: bool, owned: bool, enabled: bool) -> SilverIngestionState:
    return SilverIngestionState(
        is_linked=linked,
        is_owned_by_estate=owned,
        ingestion_enabled=enabled,
    )


_EXISTING_STATES = tuple(
    _state(linked=linked, owned=owned, enabled=enabled)
    for linked, owned, enabled in itertools.product((False, True), repeat=3)
)

_PRESENT_CASES = [
    # No row yet: adopt the catalogue's active flag.
    (None, True, IngestionTransition.ADOPT, True),
    (None, False, IngestionTransition.ADOPT, False),
    # Unlinked row owned by this estate (or unowned): adopt the catalogue.
    (
        _state(linked=False, owned=True, enabled=False),
        True,
        IngestionTransition.ADOPT,
        True,
    ),
    (
        _state(linked=False, owned=True, enabled=True),
        True,
        IngestionTransition.ADOPT,
        True,
    ),
    (
        _state(linked=False, owned=True, enabled=False),
        False,
        IngestionTransition.ADOPT,
        False,
    ),
    (
        _state(linked=False, owned=True, enabled=True),
        False,
        IngestionTransition.ADOPT,
        False,
    ),
    # Row owned by another estate: never touch it.
    (
        _state(linked=False, owned=False, enabled=False),
        True,
        IngestionTransition.CONFLICT,
        False,
    ),
    (
        _state(linked=False, owned=False, enabled=True),
        True,
        IngestionTransition.CONFLICT,
        True,
    ),
    (
        _state(linked=False, owned=False, enabled=False),
        False,
        IngestionTransition.CONFLICT,
        False,
    ),
    (
        _state(linked=False, owned=False, enabled=True),
        False,
        IngestionTransition.CONFLICT,
        True,
    ),
    (
        _state(linked=True, owned=False, enabled=False),
        True,
        IngestionTransition.CONFLICT,
        False,
    ),
    (
        _state(linked=True, owned=False, enabled=True),
        True,
        IngestionTransition.CONFLICT,
        True,
    ),
    (
        _state(linked=True, owned=False, enabled=False),
        False,
        IngestionTransition.CONFLICT,
        False,
    ),
    (
        _state(linked=True, owned=False, enabled=True),
        False,
        IngestionTransition.CONFLICT,
        True,
    ),
    # Linked row of this estate: preserve the operator's last toggle.
    (
        _state(linked=True, owned=True, enabled=False),
        True,
        IngestionTransition.PRESERVE,
        False,
    ),
    (
        _state(linked=True, owned=True, enabled=True),
        True,
        IngestionTransition.PRESERVE,
        True,
    ),
    # A linked row of this estate is disabled when the catalogue says inactive.
    (
        _state(linked=True, owned=True, enabled=False),
        False,
        IngestionTransition.DISABLE_INACTIVE,
        False,
    ),
    (
        _state(linked=True, owned=True, enabled=True),
        False,
        IngestionTransition.DISABLE_INACTIVE,
        False,
    ),
]

_REMOVED_CASES = [
    # Another estate's row is never touched.
    (
        _state(linked=False, owned=False, enabled=False),
        IngestionTransition.CONFLICT,
        False,
    ),
    (
        _state(linked=False, owned=False, enabled=True),
        IngestionTransition.CONFLICT,
        True,
    ),
    (
        _state(linked=True, owned=False, enabled=False),
        IngestionTransition.CONFLICT,
        False,
    ),
    (
        _state(linked=True, owned=False, enabled=True),
        IngestionTransition.CONFLICT,
        True,
    ),
    # An ad hoc (unlinked) row is not a catalogue row and is left alone.
    (
        _state(linked=False, owned=True, enabled=False),
        IngestionTransition.PRESERVE,
        False,
    ),
    (
        _state(linked=False, owned=True, enabled=True),
        IngestionTransition.PRESERVE,
        True,
    ),
    # A linked row of this estate that vanished from the catalogue is disabled.
    (
        _state(linked=True, owned=True, enabled=False),
        IngestionTransition.DISABLE_REMOVED,
        False,
    ),
    (
        _state(linked=True, owned=True, enabled=True),
        IngestionTransition.DISABLE_REMOVED,
        False,
    ),
]


@pytest.mark.parametrize(
    ("current", "catalogue_active", "transition", "enabled"),
    _PRESENT_CASES,
)
def test_decide_for_catalogue_repository(
    current: SilverIngestionState | None,
    *,
    catalogue_active: bool,
    transition: IngestionTransition,
    enabled: bool,
) -> None:
    """Every present-catalogue combination yields the documented decision."""
    decision = decide_for_catalogue_repository(
        current, catalogue_active=catalogue_active
    )

    assert decision == IngestionDecision(
        ingestion_enabled=enabled, transition=transition
    )


@pytest.mark.parametrize(("current", "transition", "enabled"), _REMOVED_CASES)
def test_decide_for_removed_repository(
    current: SilverIngestionState,
    transition: IngestionTransition,
    *,
    enabled: bool,
) -> None:
    """Every removed-catalogue combination yields the documented decision."""
    decision = decide_for_removed_repository(current)

    assert decision == IngestionDecision(
        ingestion_enabled=enabled, transition=transition
    )


def test_present_cases_cover_the_whole_input_space() -> None:
    """The present table is exhaustive, not a sample."""
    states: tuple[SilverIngestionState | None, ...] = (None, *_EXISTING_STATES)
    covered = {(current, active) for current, active, _, _ in _PRESENT_CASES}

    assert covered == {
        (current, active) for current in states for active in (False, True)
    }


def test_removed_cases_cover_the_whole_input_space() -> None:
    """The removed table is exhaustive over existing rows."""
    covered = {current for current, _, _ in _REMOVED_CASES}

    assert covered == set(_EXISTING_STATES)


def test_transition_vocabulary_is_stable() -> None:
    """The enum values are the operator-facing vocabulary."""
    assert {transition.value for transition in IngestionTransition} == {
        "adopt",
        "preserve",
        "disable_inactive",
        "disable_removed",
        "conflict",
    }


def test_silver_state_cannot_be_mutated() -> None:
    """Policy inputs are immutable so a decision cannot alias caller state."""
    state = _state(linked=True, owned=True, enabled=True)

    with pytest.raises(dataclasses.FrozenInstanceError):
        state.ingestion_enabled = False  # ty: ignore[invalid-assignment]
