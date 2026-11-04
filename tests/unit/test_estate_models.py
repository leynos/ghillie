"""Estate-key validation (obligation O3).

The creation pattern and the reference rule are deliberately different: an
operator creating an estate must use a routable slug, while a read or mutation
of an existing estate accepts any key of the documented maximum length so that
keys created earlier through Python remain reachable.
"""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ghillie.estate.errors import InvalidEstateKeyError
from ghillie.estate.models import (
    MAX_ESTATE_KEY_LENGTH,
    NEW_ESTATE_KEY_PATTERN,
    validate_estate_key_reference,
    validate_new_estate_key,
)

_COMPILED_PATTERN = re.compile(NEW_ESTATE_KEY_PATTERN)


@pytest.mark.parametrize(
    "estate_key",
    [
        "a",
        "demo",
        "2-5-2-estate-management-apis",
        "ABC_09.-",
        "a" * MAX_ESTATE_KEY_LENGTH,
    ],
)
def test_new_estate_key_accepts_matching_keys(estate_key: str) -> None:
    """Keys matching the creation pattern are returned unchanged."""
    assert validate_new_estate_key(estate_key) == estate_key, (
        f"{estate_key!r} should be accepted"
    )


@pytest.mark.parametrize(
    "estate_key",
    [
        "",
        "-leading-dash",
        ".leading-dot",
        "has space",
        "non-ascii-é",
        "..",
        "a/b",
        "a" * (MAX_ESTATE_KEY_LENGTH + 1),
    ],
)
def test_new_estate_key_rejects_non_matching_keys(estate_key: str) -> None:
    """Keys outside the creation pattern are rejected."""
    with pytest.raises(InvalidEstateKeyError):
        validate_new_estate_key(estate_key)


@given(st.from_regex(NEW_ESTATE_KEY_PATTERN, fullmatch=True))
def test_new_estate_key_property_accepts_pattern_matches(estate_key: str) -> None:
    """Every string generated from the pattern is accepted."""
    assert validate_new_estate_key(estate_key) == estate_key, (
        f"pattern-generated key {estate_key!r} should be accepted"
    )


@given(st.text())
def test_new_estate_key_property_matches_pattern(estate_key: str) -> None:
    """Acceptance equals a full match, for arbitrary generated strings."""
    accepted = _COMPILED_PATTERN.fullmatch(estate_key) is not None

    try:
        validate_new_estate_key(estate_key)
    except InvalidEstateKeyError:
        assert not accepted, f"{estate_key!r} should be rejected"
    else:
        assert accepted, estate_key


@pytest.mark.parametrize(
    "estate_key",
    ["a", "with space", "é", "a/b", "a" * MAX_ESTATE_KEY_LENGTH],
)
def test_reference_key_accepts_any_non_empty_key_within_the_limit(
    estate_key: str,
) -> None:
    """Existing keys of any shape remain addressable."""
    assert validate_estate_key_reference(estate_key) == estate_key, (
        f"{estate_key!r} should be accepted"
    )


@pytest.mark.parametrize(
    "estate_key",
    ["", "a" * (MAX_ESTATE_KEY_LENGTH + 1)],
)
def test_reference_key_rejects_empty_and_over_long_keys(estate_key: str) -> None:
    """The reference rule enforces only the length bound."""
    with pytest.raises(InvalidEstateKeyError):
        validate_estate_key_reference(estate_key)
