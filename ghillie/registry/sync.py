"""Catalogue-to-Silver synchronization.

This module contains the low-level implementation used by
`RepositoryRegistryService.sync_from_catalogue()` to project repository
definitions from the catalogue database into the Silver `Repository` table.

It creates missing repositories, refreshes catalogue metadata on existing ones,
and disables ingestion for repositories that were removed from the catalogue
(while keeping rows for historical reporting). The ingestion flag itself is
decided by :mod:`ghillie.registry.policy`, so a sync never re-enables a linked
row of the estate and never captures a row owned by another estate.

Example:
-------
Sync an estate and inspect the result::

    result = await sync_from_catalogue(
        catalogue_session_factory,
        silver_session_factory,
        estate_key="my-estate",
    )
    print(result.repositories_created)

"""

from __future__ import annotations

import dataclasses
import typing as typ

from sqlalchemy import Insert, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from ghillie.catalogue.storage import (
    ComponentRecord,
    Estate,
    ProjectRecord,
    RepositoryRecord,
)
from ghillie.common.slug import parse_repo_slug
from ghillie.common.time import utcnow
from ghillie.registry.errors import RegistrySyncError
from ghillie.registry.models import SyncResult
from ghillie.registry.policy import (
    IngestionDecision,
    IngestionTransition,
    SilverIngestionState,
    decide_for_catalogue_repository,
    decide_for_removed_repository,
)
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import datetime as dt

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]


async def sync_from_catalogue(
    catalogue_session_factory: SessionFactory,
    silver_session_factory: SessionFactory,
    estate_key: str,
    *,
    dry_run: bool = False,
) -> SyncResult:
    """Synchronize catalogue repositories to Silver for an estate.

    Parameters
    ----------
    catalogue_session_factory:
        Async session factory for the catalogue database.
    silver_session_factory:
        Async session factory for the Silver database.
    estate_key:
        The estate whose repositories should be synchronized.
    dry_run:
        When true, run the sync inside its transaction and roll it back,
        returning the counts it would have produced.

    Raises
    ------
    RegistrySyncError
        If the estate cannot be found or sync fails.

    """
    catalogue_repos, estate_id = await _load_catalogue_repositories_or_raise(
        catalogue_session_factory,
        estate_key,
    )
    plan = _SyncPlan(
        estate_key=estate_key,
        estate_id=estate_id,
        catalogue_repos=catalogue_repos,
    )
    return await _sync_catalogue_repositories_or_raise(
        silver_session_factory,
        plan,
        dry_run=dry_run,
    )


async def _load_catalogue_repositories_or_raise(
    session_factory: SessionFactory,
    estate_key: str,
) -> tuple[dict[str, RepositoryRecord], str]:
    """Load catalogue repositories for an estate, raising RegistrySyncError."""
    try:
        load_result = await _load_catalogue_repositories(session_factory, estate_key)
    except SQLAlchemyError as exc:
        raise RegistrySyncError(estate_key, "Database error during sync") from exc

    if load_result is None:
        raise RegistrySyncError(estate_key, "Estate not found")

    return load_result


async def _sync_catalogue_repositories_or_raise(
    session_factory: SessionFactory,
    plan: _SyncPlan,
    *,
    dry_run: bool,
) -> SyncResult:
    """Sync catalogue repositories into Silver, raising RegistrySyncError.

    A dry run rolls the transaction back, so the returned counts describe what
    a real run would have done without persisting any of it.
    """
    result = SyncResult(estate_key=plan.estate_key)
    try:
        async with session_factory() as session:
            transaction = await session.begin()
            await _sync_repositories(session, plan, result)
            if dry_run:
                # Flush first so constraints (for example the unique
                # owner/name pair) are evaluated before the rollback. Without
                # it a dry run could report counts for a sync that would fail.
                await session.flush()
                await transaction.rollback()
            else:
                await transaction.commit()
    except SQLAlchemyError as exc:
        raise RegistrySyncError(plan.estate_key, "Database error during sync") from exc
    return result


def _catalogue_repository_map(
    projects: cabc.Iterable[ProjectRecord],
) -> dict[str, RepositoryRecord]:
    """Build a slug-indexed repository map from catalogue projects."""
    repos: dict[str, RepositoryRecord] = {}
    for project in projects:
        for component in project.components:
            if component.repository is not None:
                repos[component.repository.slug] = component.repository
    return repos


async def _load_catalogue_repositories(
    session_factory: SessionFactory, estate_key: str
) -> tuple[dict[str, RepositoryRecord], str] | None:
    """Load all repositories from the catalogue for an estate."""
    async with session_factory() as session:
        estate = await session.scalar(select(Estate).where(Estate.key == estate_key))
        if estate is None:
            return None

        projects = await session.scalars(
            select(ProjectRecord)
            .where(ProjectRecord.estate_id == estate.id)
            .options(
                selectinload(ProjectRecord.components).selectinload(
                    ComponentRecord.repository
                )
            )
        )

        return _catalogue_repository_map(projects), estate.id


async def _load_silver_repositories(
    session: AsyncSession,
    estate_id: str | None,
    catalogue_slugs: cabc.Iterable[str],
) -> dict[str, Repository]:
    """Load Silver rows the sync must see for this estate.

    That means rows the estate owns or that are unowned, plus every row whose
    slug the catalogue names. The second query is what makes a row owned by
    another estate visible as a conflict instead of an attempted insert.
    """
    rows: dict[str, Repository] = {}
    owned = await session.scalars(
        select(Repository).where(
            (Repository.estate_id == estate_id) | (Repository.estate_id.is_(None))
        )
    )
    for row in owned:
        rows[row.slug] = row

    pairs = [parse_repo_slug(slug) for slug in catalogue_slugs]
    if pairs:
        named = await session.scalars(
            select(Repository).where(
                tuple_(Repository.github_owner, Repository.github_name).in_(pairs)
            )
        )
        for row in named:
            rows.setdefault(row.slug, row)
    return rows


@dataclasses.dataclass(frozen=True, slots=True)
class _SyncPlan:
    """The catalogue view a sync applies, resolved before Silver is touched."""

    estate_key: str
    estate_id: str | None
    catalogue_repos: dict[str, RepositoryRecord]


@dataclasses.dataclass(frozen=True, slots=True)
class _SilverSyncContext:
    """Context for a Silver sync transaction."""

    session: AsyncSession
    silver_repos: dict[str, Repository]
    estate_id: str | None
    now: dt.datetime
    result: SyncResult


def _silver_state(
    silver_repo: Repository,
    estate_id: str | None,
) -> SilverIngestionState:
    """Describe a Silver row in the terms the policy understands."""
    return SilverIngestionState(
        is_linked=silver_repo.catalogue_repository_id is not None,
        is_owned_by_estate=(
            silver_repo.estate_id is None or silver_repo.estate_id == estate_id
        ),
        ingestion_enabled=silver_repo.ingestion_enabled,
    )


async def _load_silver_repository(
    session: AsyncSession,
    slug: str,
    *,
    populate_existing: bool = False,
) -> Repository | None:
    """Load one Silver row by slug.

    The lookup runs in the sync's own transaction, so it observes whatever the
    racing sync already committed. ``populate_existing`` is for a re-read after
    a write lost a race: without it the identity map would return the cached
    pre-race instance and its stale attributes.
    """
    owner, name = parse_repo_slug(slug)
    statement = select(Repository).where(
        Repository.github_owner == owner,
        Repository.github_name == name,
    )
    if populate_existing:
        statement = statement.execution_options(populate_existing=True)
    return await session.scalar(statement)


def _insert_ignoring_duplicates(
    session: AsyncSession,
    row: Repository,
) -> Insert | None:
    """Build an insert that leaves an existing owner/name row untouched.

    Returns ``None`` for a dialect without an upsert construct, so the caller
    can fall back to a plain insert. A savepoint would be the portable
    alternative, but pysqlite's legacy transaction mode commits on
    ``RELEASE SAVEPOINT``, which would make a dry run persist its rows.
    """
    values = {
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
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        return postgresql_insert(Repository).values(**values).on_conflict_do_nothing()
    if dialect_name == "sqlite":
        return sqlite_insert(Repository).values(**values).on_conflict_do_nothing()
    return None


async def _insert_or_reconcile(
    context: _SilverSyncContext,
    slug: str,
    cat_repo: RepositoryRecord,
    decision: IngestionDecision,
) -> None:
    """Insert a new Silver row, reporting a lost insert race as a conflict.

    Two estates can name the same repository and sync at the same time. Both
    then read no row and both try to insert; ``uq_repositories_owner_name``
    lets only one succeed. Ignoring the duplicate lets the losing sync re-read
    the winner and run the ordinary decision path again, so a row owned by
    another estate is reported in ``repositories_conflicted`` instead of
    aborting the whole sync.

    A conflict that leaves no row behind is not an owner/name race, so the
    plain insert runs and its ``IntegrityError`` reaches the caller for the
    409 mapping.
    """
    row = _create_silver_repository(cat_repo, context, decision)
    statement = _insert_ignoring_duplicates(context.session, row)
    if statement is not None:
        inserted_id = await context.session.scalar(statement.returning(Repository.id))
        if inserted_id is not None:
            context.result.repositories_created += 1
            return

        winner = await _load_silver_repository(context.session, slug)
        if winner is not None:
            context.silver_repos[slug] = winner
            await _sync_one_repository(context, slug, cat_repo)
            return

    # Either the dialect has no upsert construct, or the conflict left no row
    # behind. A plain insert then succeeds or raises the constraint failure
    # that the caller maps to 409.
    context.session.add(row)
    await context.session.flush()
    context.result.repositories_created += 1


async def _claim_unowned_repository(
    session: AsyncSession,
    silver_repo: Repository,
    estate_id: str | None,
) -> bool:
    """Claim an unowned Silver row for this estate, returning False if lost.

    An unowned row is adoptable by any estate, so two syncs for different
    estates can both decide to claim it. The owner/name uniqueness constraint
    arbitrates a race to *insert* the same repository; it cannot arbitrate a
    race to adopt an existing row, because changing `estate_id` leaves the
    owner/name pair unique. A conditional UPDATE makes the claim itself
    atomic, so the loser updates nothing and must report a conflict instead of
    overwriting the winner's claim.
    """
    if estate_id is None or silver_repo.estate_id is not None:
        return True

    claimed_id = await session.scalar(
        update(Repository)
        .where(Repository.id == silver_repo.id, Repository.estate_id.is_(None))
        .values(estate_id=estate_id)
        .returning(Repository.id)
        .execution_options(synchronize_session=False)
    )
    if claimed_id is None:
        return False

    # The statement bypassed the identity map, so mirror the claim locally.
    silver_repo.estate_id = estate_id
    return True


async def _reload_after_lost_claim(
    session: AsyncSession,
    slug: str,
) -> Repository | None:
    """Re-read a row whose conditional claim matched nothing.

    The caller's view predates the winning claim, so ownership must be judged
    from the database rather than the identity map. ``populate_existing`` is
    what makes that true: a plain select would return the cached pre-claim
    instance, and the losing sync would then overwrite the winner's claim.
    """
    return await _load_silver_repository(session, slug, populate_existing=True)


async def _sync_one_repository(
    context: _SilverSyncContext,
    slug: str,
    cat_repo: RepositoryRecord,
) -> None:
    """Sync a single catalogue repository into Silver."""
    silver_repo = context.silver_repos.get(slug)
    current = (
        None if silver_repo is None else _silver_state(silver_repo, context.estate_id)
    )
    decision = decide_for_catalogue_repository(
        current, catalogue_active=cat_repo.is_active
    )

    if decision.transition is IngestionTransition.CONFLICT:
        context.result.repositories_conflicted.append(slug)
        return

    if silver_repo is None:
        await _insert_or_reconcile(context, slug, cat_repo, decision)
        return

    if not await _claim_unowned_repository(
        context.session, silver_repo, context.estate_id
    ):
        # The claim lost, but not necessarily to another estate: a concurrent
        # sync of this same estate can have adopted the row. Judge ownership
        # from the committed state, and continue the sync when the row is ours.
        refreshed = await _reload_after_lost_claim(context.session, slug)
        if refreshed is None:
            context.result.repositories_conflicted.append(slug)
            return
        silver_repo = refreshed
        context.silver_repos[slug] = refreshed
        current = _silver_state(refreshed, context.estate_id)
        if not current.is_owned_by_estate:
            context.result.repositories_conflicted.append(slug)
            return
        decision = decide_for_catalogue_repository(
            current, catalogue_active=cat_repo.is_active
        )

    changed = _update_silver_repository(context, silver_repo, cat_repo, decision)
    if changed:
        context.result.repositories_updated += 1

    if (
        decision.transition is IngestionTransition.PRESERVE
        and not decision.ingestion_enabled
    ):
        context.result.note_left_disabled(slug)


async def _sync_repositories(
    session: AsyncSession,
    plan: _SyncPlan,
    result: SyncResult,
) -> None:
    """Project catalogue repositories into Silver, updating or creating."""
    silver_repos = await _load_silver_repositories(
        session, plan.estate_id, plan.catalogue_repos
    )

    context = _SilverSyncContext(
        session=session,
        silver_repos=silver_repos,
        estate_id=plan.estate_id,
        now=utcnow(),
        result=result,
    )

    # One sorted pass over both phases, flushing each slug before the next.
    # Two estates syncing the same repositories must take their row locks in
    # the same order, or each can hold a row the other is waiting for and
    # Postgres resolves it by aborting one of them. Catalogue order is not
    # guaranteed to agree between estates, and a separate removal pass would
    # give the two phases two different orders, so the union is walked once and
    # every write for a slug is flushed before the next slug is touched.
    for slug in sorted(set(plan.catalogue_repos) | set(silver_repos)):
        if slug in plan.catalogue_repos:
            await _sync_one_repository(context, slug, plan.catalogue_repos[slug])
        else:
            _deactivate_removed_repository(context, slug)
        await session.flush()


def _create_silver_repository(
    cat_repo: RepositoryRecord,
    context: _SilverSyncContext,
    decision: IngestionDecision,
) -> Repository:
    """Create a new Silver repository from a catalogue record."""
    return Repository(
        github_owner=cat_repo.owner,
        github_name=cat_repo.name,
        default_branch=cat_repo.default_branch,
        estate_id=context.estate_id,
        catalogue_repository_id=cat_repo.id,
        ingestion_enabled=decision.ingestion_enabled,
        documentation_paths=list(cat_repo.documentation_paths),
        last_synced_at=context.now,
    )


def _deactivate_removed_repository(
    context: _SilverSyncContext,
    slug: str,
) -> None:
    """Deactivate one repository that is no longer in this estate's catalogue."""
    silver_repo = context.silver_repos[slug]
    decision = decide_for_removed_repository(
        _silver_state(silver_repo, context.estate_id)
    )
    if decision.transition is not IngestionTransition.DISABLE_REMOVED:
        return
    if not silver_repo.ingestion_enabled:
        return
    silver_repo.ingestion_enabled = False
    silver_repo.last_synced_at = context.now
    context.result.repositories_deactivated += 1


def _update_silver_repository(
    context: _SilverSyncContext,
    silver_repo: Repository,
    cat_repo: RepositoryRecord,
    decision: IngestionDecision,
) -> bool:
    """Update Silver repository fields from catalogue; return True if changed."""
    # Define field mappings: (silver_field, catalogue_value)
    field_updates = [
        ("default_branch", cat_repo.default_branch),
        ("estate_id", context.estate_id),
        ("catalogue_repository_id", cat_repo.id),
    ]

    changed = False

    # Apply scalar field updates
    for field_name, new_value in field_updates:
        if getattr(silver_repo, field_name) != new_value:
            setattr(silver_repo, field_name, new_value)
            changed = True

    # The policy owns ingestion; metadata never implies a toggle change.
    if silver_repo.ingestion_enabled != decision.ingestion_enabled:
        silver_repo.ingestion_enabled = decision.ingestion_enabled
        changed = True

    # Handle documentation_paths separately (list comparison)
    new_paths = list(cat_repo.documentation_paths)
    if silver_repo.documentation_paths != new_paths:
        silver_repo.documentation_paths = new_paths
        changed = True

    if changed:
        silver_repo.last_synced_at = context.now

    return changed
