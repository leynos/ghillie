"""Silver persistence statements for registry sync.

:mod:`ghillie.registry.sync` decides what a sync should do; this module owns
the SQL that does it. Each helper returns an explicit outcome, so the caller
can tell "this sync made the change" from "another writer got there first"
without inspecting row counts or catching constraint errors.

The upsert is a strategy rather than a dialect branch buried in a statement
builder. `DialectUpsertStrategy` is the default the service installs;
deployments and tests can substitute any `UpsertStrategy`, and a dialect
without an upsert construct uses the named `PlainInsertStrategy` fallback.
"""

from __future__ import annotations

import enum
import typing as typ

from sqlalchemy import Insert, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    import datetime as dt

    from sqlalchemy.ext.asyncio import AsyncSession


class UpsertStrategy(typ.Protocol):
    """Builds an insert that leaves a conflicting owner/name row untouched.

    An implementation returns ``None`` when it cannot express the upsert; the
    caller then inserts plainly and lets the uniqueness constraint speak.
    """

    def build(self, session: AsyncSession, row: Repository) -> Insert | None:
        """Return the upsert statement for ``row``, or ``None`` to decline."""
        ...


def _insert_values(row: Repository) -> dict[str, object]:
    """Return the column values an insert of ``row`` carries."""
    values: dict[str, object] = {
        "github_owner": row.github_owner,
        "github_name": row.github_name,
        "default_branch": row.default_branch,
        "estate_id": row.estate_id,
        "catalogue_repository_id": row.catalogue_repository_id,
        "ingestion_enabled": row.ingestion_enabled,
        "documentation_paths": row.documentation_paths,
        "last_synced_at": row.last_synced_at,
    }
    if row.id is not None:
        # An id assigned by the caller wins over the column default, so a
        # collision on it is visible rather than silently replaced.
        values["id"] = row.id
    return values


class PostgresUpsertStrategy:
    """Insert on PostgreSQL, ignoring an owner/name conflict."""

    def build(self, session: AsyncSession, row: Repository) -> Insert:
        """Return a PostgreSQL insert that does nothing on a conflict."""
        return (
            postgresql_insert(Repository)
            .values(**_insert_values(row))
            .on_conflict_do_nothing()
        )


class SqliteUpsertStrategy:
    """Insert on SQLite, ignoring an owner/name conflict."""

    def build(self, session: AsyncSession, row: Repository) -> Insert:
        """Return a SQLite insert that does nothing on a conflict."""
        return (
            sqlite_insert(Repository)
            .values(**_insert_values(row))
            .on_conflict_do_nothing()
        )


class PlainInsertStrategy:
    """Decline the upsert so the caller inserts through the session.

    This is the named fallback for a dialect without an upsert construct. A
    savepoint would be the portable alternative, but pysqlite's legacy
    transaction mode commits on ``RELEASE SAVEPOINT``, which would make a dry
    run persist its rows. The caller's plain insert then either succeeds or
    raises the constraint failure that maps to 409.
    """

    def build(self, session: AsyncSession, row: Repository) -> None:
        """Decline, leaving the insert to the caller."""


_POSTGRES_UPSERT = PostgresUpsertStrategy()
_SQLITE_UPSERT = SqliteUpsertStrategy()
_PLAIN_INSERT = PlainInsertStrategy()


def dialect_upsert_strategy(dialect_name: str) -> UpsertStrategy:
    """Return the named upsert strategy for ``dialect_name``.

    Unknown dialects get the plain-insert fallback rather than an error, so a
    new backend degrades to "insert, then let the constraint arbitrate"
    instead of failing every sync.
    """
    if dialect_name == "postgresql":
        return _POSTGRES_UPSERT
    if dialect_name == "sqlite":
        return _SQLITE_UPSERT
    return _PLAIN_INSERT


class DialectUpsertStrategy:
    """Resolve the named strategy from the session's dialect.

    The service installs this by default, which keeps the dialect discovery in
    one place. Tests and alternative deployments substitute an `UpsertStrategy`
    directly, so the choice is no longer hidden inside a statement builder.
    """

    def build(self, session: AsyncSession, row: Repository) -> Insert | None:
        """Build the upsert the session's dialect supports, if any."""
        strategy = dialect_upsert_strategy(session.get_bind().dialect.name)
        return strategy.build(session, row)


class InsertOutcome(enum.Enum):
    """What an insert attempt established about the owner/name pair."""

    INSERTED = "inserted"
    """This sync inserted the row."""

    CONFLICT = "conflict"
    """A competing row existed; the caller should reconcile with it."""

    DECLINED = "declined"
    """The strategy supplied no upsert, so the caller inserts plainly."""


async def insert_ignoring_duplicates(
    session: AsyncSession,
    row: Repository,
    strategy: UpsertStrategy,
) -> InsertOutcome:
    """Insert ``row`` unless an owner/name row already exists.

    Returns
    -------
    InsertOutcome
        ``INSERTED`` when this sync inserted the row, ``CONFLICT`` when a
        competing row won, and ``DECLINED`` when the strategy supplied no
        upsert. Declining is not an error: the caller then inserts plainly and
        lets the uniqueness constraint speak.

    """
    statement = strategy.build(session, row)
    if statement is None:
        return InsertOutcome.DECLINED
    inserted_id = await session.scalar(statement.returning(Repository.id))
    if inserted_id is None:
        return InsertOutcome.CONFLICT
    return InsertOutcome.INSERTED


async def insert_plainly(session: AsyncSession, row: Repository) -> None:
    """Insert ``row`` through the session, raising on any constraint failure."""
    session.add(row)
    await session.flush()


async def claim_unowned_repository(
    session: AsyncSession,
    repository: Repository,
    estate_id: str | None,
) -> bool:
    """Claim an unowned Silver row for this estate, returning False if lost.

    An unowned row is adoptable by any estate, so two syncs for different
    estates can both decide to claim it. The owner/name uniqueness constraint
    arbitrates a race to *insert* the same repository; it cannot arbitrate a
    race to adopt an existing row, because changing ``estate_id`` leaves the
    owner/name pair unique. The conditional UPDATE makes the claim itself
    atomic, so the loser updates nothing and re-reads the committed row.

    The statement bypasses the identity map, so a successful claim is mirrored
    onto the loaded instance by the caller before it continues.
    """
    if estate_id is None or repository.estate_id is not None:
        return True

    claimed_id = await session.scalar(
        update(Repository)
        .where(Repository.id == repository.id, Repository.estate_id.is_(None))
        .values(estate_id=estate_id)
        .returning(Repository.id)
        .execution_options(synchronize_session=False)
    )
    return claimed_id is not None


async def deactivate_if_still_enabled(
    session: AsyncSession,
    repository: Repository,
    estate_id: str | None,
    now: dt.datetime,
) -> bool:
    """Disable one removed repository, returning whether this sync did it.

    The loaded view can be stale. A row this sync read as unowned may have been
    claimed by another estate before this write, and the removal path would
    then disable a repository the policy forbids it to touch. The ownership
    condition therefore travels with the UPDATE, so a claim that landed after
    the load leaves no row to match.

    The enabled condition travels with the UPDATE for the same reason. The
    count and ``last_synced_at`` describe what *this* sync changed, so a row an
    operator (or an earlier sync) disabled after the load must not be counted
    again or restamped.

    The statement synchronizes the session by fetch, so the loaded instance
    adopts the committed values without an assignment that would queue an
    unconditional UPDATE on the next flush and defeat the guard.
    """
    deactivated_id = await session.scalar(
        update(Repository)
        .where(
            Repository.id == repository.id,
            Repository.estate_id.is_(None) | (Repository.estate_id == estate_id),
            Repository.ingestion_enabled.is_(True),
        )
        .values(ingestion_enabled=False, last_synced_at=now)
        .returning(Repository.id)
        .execution_options(synchronize_session="fetch")
    )
    return deactivated_id is not None
