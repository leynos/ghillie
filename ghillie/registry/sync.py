"""Catalogue-to-Silver synchronization.

This module contains the low-level implementation used by
`RepositoryRegistryService.sync_from_catalogue()` to project repository
definitions from the catalogue database into the Silver `Repository` table.

It creates missing repositories, updates existing ones to match catalogue
state, and disables ingestion for repositories that were removed from the
catalogue (while keeping rows for historical reporting).

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

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from ghillie.catalogue.storage import (
    ComponentRecord,
    Estate,
    ProjectRecord,
    RepositoryRecord,
)
from ghillie.common.time import utcnow
from ghillie.registry.errors import RegistrySyncError
from ghillie.registry.models import SyncResult
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
) -> SyncResult:
    """Synchronize catalogue repositories to Silver for an estate.

    Raises
    ------
    RegistrySyncError
        If the estate cannot be found or sync fails.

    """
    result = SyncResult(estate_key=estate_key)

    catalogue_repos, estate_id = await _load_catalogue_repositories_or_raise(
        catalogue_session_factory,
        estate_key,
    )
    await _sync_catalogue_repositories_or_raise(
        silver_session_factory,
        catalogue_repos,
        estate_id,
        result,
    )

    return result


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
    catalogue_repos: dict[str, RepositoryRecord],
    estate_id: str | None,
    result: SyncResult,
) -> None:
    """Sync catalogue repositories into Silver, raising RegistrySyncError."""
    try:
        async with session_factory() as session, session.begin():
            await _sync_repositories(session, catalogue_repos, estate_id, result)
    except SQLAlchemyError as exc:
        raise RegistrySyncError(
            result.estate_key, "Database error during sync"
        ) from exc


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
) -> dict[str, Repository]:
    """Load Silver repositories that could belong to an estate sync run."""
    query = select(Repository)
    if estate_id is not None:
        query = query.where(
            (Repository.estate_id == estate_id) | (Repository.estate_id.is_(None))
        )
    existing = await session.scalars(query)
    return {repo.slug: repo for repo in existing}


@dataclasses.dataclass(frozen=True, slots=True)
class _SilverSyncContext:
    """Context for a Silver sync transaction."""

    session: AsyncSession
    silver_repos: dict[str, Repository]
    estate_id: str | None
    now: dt.datetime
    result: SyncResult


def _sync_one_repository(
    context: _SilverSyncContext,
    slug: str,
    cat_repo: RepositoryRecord,
) -> None:
    """Sync a single catalogue repository into Silver."""
    silver_repo = context.silver_repos.get(slug)
    if silver_repo is None:
        context.session.add(
            _create_silver_repository(cat_repo, context.estate_id, context.now)
        )
        context.result.repositories_created += 1
        return

    changed = _update_silver_repository(
        silver_repo,
        cat_repo,
        context.estate_id,
        context.now,
    )
    if changed:
        context.result.repositories_updated += 1


async def _sync_repositories(
    session: AsyncSession,
    catalogue_repos: dict[str, RepositoryRecord],
    estate_id: str | None,
    result: SyncResult,
) -> None:
    """Project catalogue repositories into Silver, updating or creating."""
    silver_repos = await _load_silver_repositories(session, estate_id)

    now = utcnow()
    seen_slugs = set(catalogue_repos)
    context = _SilverSyncContext(
        session=session,
        silver_repos=silver_repos,
        estate_id=estate_id,
        now=now,
        result=result,
    )

    for slug, cat_repo in catalogue_repos.items():
        _sync_one_repository(context, slug, cat_repo)

    _deactivate_removed_repositories(silver_repos, seen_slugs, now, result)


def _create_silver_repository(
    cat_repo: RepositoryRecord,
    estate_id: str | None,
    now: dt.datetime,
) -> Repository:
    """Create a new Silver repository from a catalogue record."""
    return Repository(
        github_owner=cat_repo.owner,
        github_name=cat_repo.name,
        default_branch=cat_repo.default_branch,
        estate_id=estate_id,
        catalogue_repository_id=cat_repo.id,
        ingestion_enabled=cat_repo.is_active,
        documentation_paths=list(cat_repo.documentation_paths),
        last_synced_at=now,
    )


def _should_deactivate_repository(
    slug: str,
    silver_repo: Repository,
    seen_slugs: set[str],
) -> bool:
    """Determine whether a Silver repository should be deactivated."""
    return (
        slug not in seen_slugs
        and silver_repo.catalogue_repository_id is not None
        and silver_repo.ingestion_enabled
    )


def _deactivate_removed_repositories(
    silver_repos: dict[str, Repository],
    seen_slugs: set[str],
    now: dt.datetime,
    result: SyncResult,
) -> None:
    """Deactivate repositories that are no longer in the catalogue."""
    for slug, silver_repo in silver_repos.items():
        if _should_deactivate_repository(slug, silver_repo, seen_slugs):
            silver_repo.ingestion_enabled = False
            silver_repo.last_synced_at = now
            result.repositories_deactivated += 1


def _update_silver_repository(
    silver_repo: Repository,
    cat_repo: RepositoryRecord,
    estate_id: str | None,
    now: dt.datetime,
) -> bool:
    """Update Silver repository fields from catalogue; return True if changed."""
    # Define field mappings: (silver_field, catalogue_value)
    field_updates = [
        ("default_branch", cat_repo.default_branch),
        ("estate_id", estate_id),
        ("catalogue_repository_id", cat_repo.id),
        ("ingestion_enabled", cat_repo.is_active),
    ]

    changed = False

    # Apply scalar field updates
    for field_name, new_value in field_updates:
        if getattr(silver_repo, field_name) != new_value:
            setattr(silver_repo, field_name, new_value)
            changed = True

    # Handle documentation_paths separately (list comparison)
    new_paths = list(cat_repo.documentation_paths)
    if silver_repo.documentation_paths != new_paths:
        silver_repo.documentation_paths = new_paths
        changed = True

    if changed:
        silver_repo.last_synced_at = now

    return changed
