"""Unit coverage for the shared estate test helpers."""

from tests.unit.estate_test_helpers import data_writes


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
