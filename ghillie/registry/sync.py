"""Catalogue-to-Silver synchronization."""

from __future__ import annotations

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

    try:
        load_result = await _load_catalogue_repositories(
            catalogue_session_factory, estate_key
        )
    except SQLAlchemyError as exc:
        raise RegistrySyncError(estate_key, "Database error during sync") from exc

    if load_result is None:
        raise RegistrySyncError(estate_key, "Estate not found")

    catalogue_repos, estate_id = load_result

    try:
        async with silver_session_factory() as session, session.begin():
            await _sync_repositories(session, catalogue_repos, estate_id, result)
    except SQLAlchemyError as exc:
        raise RegistrySyncError(estate_key, "Database error during sync") from exc

    return result


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

        repos: dict[str, RepositoryRecord] = {}
        for project in projects:
            for component in project.components:
                if component.repository is not None:
                    repos[component.repository.slug] = component.repository

        return repos, estate.id


async def _sync_repositories(
    session: AsyncSession,
    catalogue_repos: dict[str, RepositoryRecord],
    estate_id: str | None,
    result: SyncResult,
) -> None:
    """Project catalogue repositories into Silver, updating or creating."""
    query = select(Repository)
    if estate_id is not None:
        query = query.where(
            (Repository.estate_id == estate_id) | (Repository.estate_id.is_(None))
        )
    existing = await session.scalars(query)
    silver_repos: dict[str, Repository] = {repo.slug: repo for repo in existing}

    now = utcnow()
    seen_slugs: set[str] = set()

    for slug, cat_repo in catalogue_repos.items():
        seen_slugs.add(slug)

        if slug in silver_repos:
            silver_repo = silver_repos[slug]
            changed = _update_silver_repository(silver_repo, cat_repo, estate_id, now)
            if changed:
                result.repositories_updated += 1
            continue

        silver_repo = _create_silver_repository(cat_repo, estate_id, now)
        session.add(silver_repo)
        result.repositories_created += 1

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
    changed = False

    if silver_repo.default_branch != cat_repo.default_branch:
        silver_repo.default_branch = cat_repo.default_branch
        changed = True

    if silver_repo.estate_id != estate_id:
        silver_repo.estate_id = estate_id
        changed = True

    if silver_repo.catalogue_repository_id != cat_repo.id:
        silver_repo.catalogue_repository_id = cat_repo.id
        changed = True

    if silver_repo.ingestion_enabled != cat_repo.is_active:
        silver_repo.ingestion_enabled = cat_repo.is_active
        changed = True

    new_paths = list(cat_repo.documentation_paths)
    if silver_repo.documentation_paths != new_paths:
        silver_repo.documentation_paths = new_paths
        changed = True

    if changed:
        silver_repo.last_synced_at = now

    return changed
