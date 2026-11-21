"""Unit coverage for the shared estate test helpers.

The point cases below are readable regressions. The property tests beside them
pin the invariant the filter exists for: a statement that passes
``data_writes`` cannot write.
"""

import string
import typing as typ

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.unit.estate_test_helpers import _READ_PRAGMA_NAMES, data_writes

_WRITE_STATEMENTS = (
    "INSERT INTO estates (key) VALUES ('a')",
    "UPDATE estates SET name = 'a'",
    "DELETE FROM estates WHERE key = 'a'",
    "REPLACE INTO estates (key) VALUES ('a')",
    "CREATE TABLE scratch (id INTEGER)",
    "DROP TABLE scratch",
    "ALTER TABLE estates ADD COLUMN extra TEXT",
)
_CASE_TRANSFORMS = (str, str.upper, str.lower, str.swapcase)
_SQL_FILLER = st.text(alphabet=string.ascii_lowercase + " ", max_size=6)
_LEADING_NOISE = st.lists(
    st.one_of(
        st.sampled_from((" ", "\t", "\n", "   ")),
        _SQL_FILLER.map("-- {}\n".format),
        _SQL_FILLER.map("/* {} */".format),
    ),
    max_size=3,
).map("".join)
# SQLite documents these as getters. Pinned here independently of the filter's
# own list, so a change to that list fails the guard test below instead of
# silently redefining what the properties treat as verified.
_VERIFIED_GETTERS = (
    "database_list",
    "foreign_key_list",
    "index_info",
    "index_list",
    "index_xinfo",
    "table_info",
    "table_xinfo",
)
# SQLite pragma names are case-insensitive, so the alphabet carries both cases.
# Drawing only lowercase names would leave the filter's lowercasing untested.
_PRAGMA_NAME_ALPHABET = string.ascii_letters + string.digits + "_"
_PRAGMA_NAMES = st.text(alphabet=_PRAGMA_NAME_ALPHABET, min_size=1, max_size=12)
_KNOWN_GETTERS = st.sampled_from(_VERIFIED_GETTERS)
_UNVERIFIED_PRAGMA_NAMES = st.text(
    alphabet=_PRAGMA_NAME_ALPHABET, min_size=1, max_size=12
).filter(lambda name: name.lower() not in _VERIFIED_GETTERS)
_SCHEMA_PREFIXES = st.sampled_from(("", "main.", "temp."))


def _assert_reported(statement: str) -> None:
    """Fail unless the filter reports *statement* as a write."""
    assert data_writes([statement]) == [statement], statement


@st.composite
def write_statements(draw: st.DrawFn) -> str:
    """Build a statement naming a write verb, obscured only cosmetically.

    Comments, odd case, extra whitespace, and a ``WITH`` prefix all leave the
    statement a write for SQLite, so a filter that recognises the verb must
    still report it.
    """
    statement = draw(st.sampled_from(_WRITE_STATEMENTS))
    if draw(st.booleans()):
        statement = f"WITH chosen AS (SELECT 1) {statement}"
    statement = draw(st.sampled_from(_CASE_TRANSFORMS))(statement)
    return draw(_LEADING_NOISE) + statement


def test_select_is_not_a_write() -> None:
    """A plain read passes the filter."""
    statement = "SELECT estates.id FROM estates"

    assert data_writes([statement]) == [], "a SELECT should not be reported"


def test_pragma_is_not_a_write() -> None:
    """The one pragma form the read-only checks issue passes the filter."""
    statement = "PRAGMA main.table_info('estates')"

    assert data_writes([statement]) == [], "a table_info PRAGMA should not be reported"


def test_pragma_assignment_is_reported() -> None:
    """A pragma that assigns state is a write even though it changes no row.

    ``PRAGMA user_version = 7`` rewrites the database header, which row-count
    assertions cannot see, so the filter must report it.
    """
    statement = "PRAGMA user_version = 7"

    assert data_writes([statement]) == [statement], (
        "a pragma assignment should be reported"
    )


def test_pragma_outside_the_verified_read_forms_is_reported() -> None:
    """A pragma the filter cannot prove is a getter fails closed.

    SQLite accepts ``PRAGMA journal_mode(WAL)`` as an assignment form, so a
    parenthesised pragma is only a read when its name is on the verified list.
    """
    statement = "PRAGMA journal_mode(WAL)"

    assert data_writes([statement]) == [statement], (
        "an unverified pragma form should be reported"
    )


def test_explain_analyze_update_is_reported() -> None:
    """``EXPLAIN ANALYZE`` executes the statement it explains.

    PostgreSQL runs the underlying update, and the row counts are unchanged,
    so accepting every ``EXPLAIN`` would let a write slip past a read-only
    check.
    """
    statement = "EXPLAIN ANALYZE UPDATE estates SET name = 'changed'"

    assert data_writes([statement]) == [statement], (
        "an execution-capable EXPLAIN should be reported"
    )


def test_write_verbs_are_reported() -> None:
    """Each statement form that can change rows is reported."""
    statements = [
        "INSERT INTO estates (key) VALUES (?)",
        "UPDATE estates SET name = ?",
        "DELETE FROM estates WHERE key = ?",
        "REPLACE INTO estates (key) VALUES (?)",
    ]

    assert data_writes(statements) == statements, "every write should be reported"


def test_line_comment_before_a_write_is_reported() -> None:
    """A write preceded by a ``--`` comment is still a write.

    SQLite accepts comments before a statement, so a first-word check that
    ignored them would let a commented update slip past the read-only checks.
    """
    statement = "-- audit trail\nUPDATE estates SET name = 'changed'"

    assert data_writes([statement]) == [statement], (
        "a commented write should be reported"
    )


def test_block_comment_before_a_write_is_reported() -> None:
    """A write preceded by a ``/* ... */`` comment is still a write."""
    statement = "/* audit */ UPDATE estates SET name = 'changed'"

    assert data_writes([statement]) == [statement], (
        "a block-commented write should be reported"
    )


def test_cte_before_a_write_is_reported() -> None:
    """A write behind a ``WITH`` clause is reported.

    The filter cannot classify a ``WITH`` form as a read, so it fails closed:
    a statement it does not recognise counts as a write.
    """
    statement = (
        "WITH chosen AS (SELECT id FROM estates) UPDATE estates SET name = 'changed'"
    )

    assert data_writes([statement]) == [statement], (
        "a CTE-prefixed write should be reported"
    )


def test_unrecognised_statement_is_reported() -> None:
    """A statement the filter cannot classify fails closed."""
    statement = "VACUUM"

    assert data_writes([statement]) == [statement], (
        "an unclassified statement should be reported"
    )


def test_whitespace_only_statement_is_reported() -> None:
    """A blank statement is not silently accepted as a read."""
    assert data_writes(["   \n\t"]) == ["   \n\t"], "a blank statement should fail"


@given(statement=write_statements())
def test_property_a_statement_that_passes_the_filter_cannot_write(
    statement: str,
) -> None:
    """Invariant: a statement that passes ``data_writes`` cannot write.

    Every generated statement names a write verb behind comments, case changes,
    or a ``WITH`` prefix. Accepting any of them would let a write reach the
    database while a read-only check reported nothing.
    """
    _assert_reported(statement)


@given(name=_PRAGMA_NAMES, prefix=_SCHEMA_PREFIXES, value=st.integers())
def test_property_every_pragma_assignment_is_reported(
    name: str, prefix: str, value: int
) -> None:
    """Invariant: a PRAGMA that assigns state is never accepted as a read."""
    _assert_reported(f"PRAGMA {prefix}{name} = {value}")


@given(name=_PRAGMA_NAMES, prefix=_SCHEMA_PREFIXES)
def test_property_a_pragma_call_form_is_accepted_only_for_a_verified_getter(
    name: str, prefix: str
) -> None:
    """Invariant: a call form is a read exactly when its bare form is.

    ``PRAGMA journal_mode(WAL)`` assigns, so a filter that accepted every call
    form would accept a write. Tying the call form's verdict to the bare
    getter's keeps the two spellings consistent, including for a schema prefix.
    """
    bare = f"PRAGMA {prefix}{name}"
    call = f"PRAGMA {prefix}{name}(x)"
    call_is_read = data_writes([call]) == []
    bare_is_read = data_writes([bare]) == []

    assert call_is_read == bare_is_read, (bare, call)


def test_the_verified_getter_list_matches_the_filter() -> None:
    """The property's independent getter list is the one the filter accepts."""
    assert frozenset(_VERIFIED_GETTERS) == _READ_PRAGMA_NAMES, (
        "the filter's verified pragma list changed; update this test's list"
    )


@pytest.mark.parametrize(
    "spelling", [str.upper, str.title, str.swapcase], ids=lambda fn: fn.__name__
)
def test_a_verified_getter_is_read_in_any_letter_case(
    spelling: typ.Callable[[str], str],
) -> None:
    """A getter keeps its read verdict when its name changes case.

    SQLite matches pragma names without regard to case, so ``PRAGMA
    TABLE_INFO('estates')`` is the same getter. The mixed-case names the
    property draws only prove the filter agrees if the filter really folds
    case, which this pins on one known name.
    """
    name = spelling("table_info")

    assert data_writes([f"PRAGMA {name}"]) == [], name
    assert data_writes([f"PRAGMA main.{name}('estates')"]) == [], name


@given(name=_KNOWN_GETTERS, prefix=_SCHEMA_PREFIXES)
def test_property_a_verified_getter_is_read_in_both_forms(
    name: str, prefix: str
) -> None:
    """Invariant: a documented getter passes the filter with or without a call."""
    bare = f"PRAGMA {prefix}{name}"
    call = f"PRAGMA {prefix}{name}(x)"

    assert data_writes([bare]) == [], bare
    assert data_writes([call]) == [], call


@given(name=_UNVERIFIED_PRAGMA_NAMES, prefix=_SCHEMA_PREFIXES)
def test_property_an_unverified_pragma_name_is_reported_in_both_forms(
    name: str, prefix: str
) -> None:
    """Invariant: a name outside the documented getters is reported either way.

    The generated names cannot appear on the verified getter list, in any
    letter case, so neither spelling of them may pass the filter.
    """
    bare = f"PRAGMA {prefix}{name}"
    call = f"PRAGMA {prefix}{name}(x)"

    _assert_reported(bare)
    _assert_reported(call)
