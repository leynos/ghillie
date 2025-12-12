"""Repository registry service for managing GitHub ingestion targets.

The registry service bridges the catalogue domain (source of truth for estate
configuration) with the Silver layer (operational data store for ingestion
and reporting).
"""

from __future__ import annotations

import typing as typ

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from ghillie.catalogue.storage import (
    ComponentRecord,
    Estate,
    ProjectRecord,
    RepositoryRecord,
)
from ghillie.common.time import utcnow
from ghillie.registry.errors import RegistrySyncError, RepositoryNotFoundError
from ghillie.registry.models import RepositoryInfo, SyncResult
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    import datetime as dt

type SessionFactory = async_sessionmaker[AsyncSession]


class RepositoryRegistryService:
    """Manages the registry of repositories eligible for GitHub ingestion.

    This service bridges the catalogue domain (source of truth for estate
    configuration) with the Silver layer (operational data store for ingestion
    and reporting).

    Parameters
    ----------
    catalogue_session_factory:
        Async session factory for the catalogue database.
    silver_session_factory:
        Async session factory for the Silver database.

    """

    def __init__(
        self,
        catalogue_session_factory: SessionFactory,
        silver_session_factory: SessionFactory,
    ) -> None:
        """Configure the service with session factories for both databases."""
        self._catalogue_sf = catalogue_session_factory
        self._silver_sf = silver_session_factory

    async def sync_from_catalogue(self, estate_key: str) -> SyncResult:
        """Synchronise all catalogue repositories to Silver for an estate.

        Reads repositories from the catalogue database (via component
        definitions) and projects them into the Silver repository table.
        Repositories no longer in the catalogue have ingestion disabled
        but are not deleted to preserve historical data.

        Parameters
        ----------
        estate_key:
            The estate whose repositories should be synchronised.

        Returns
        -------
        SyncResult
            Summary of created, updated, and deactivated repositories.

        Raises
        ------
        RegistrySyncError
            If the estate cannot be found or sync fails.

        """
        result = SyncResult(estate_key=estate_key)

        # Load catalogue repositories and estate_id for the estate
        load_result = await self._load_catalogue_repositories(estate_key)
        if load_result is None:
            raise RegistrySyncError(estate_key, "Estate not found")

        catalogue_repos, estate_id = load_result

        # Sync to Silver
        async with self._silver_sf() as session, session.begin():
            await self._sync_repositories(session, catalogue_repos, estate_id, result)

        return result

    async def _load_catalogue_repositories(
        self, estate_key: str
    ) -> tuple[dict[str, RepositoryRecord], str] | None:
        """Load all repositories from the catalogue for an estate.

        Returns a tuple of (repos dict mapping slug to RepositoryRecord, estate_id),
        or None if the estate does not exist.
        """
        async with self._catalogue_sf() as session:
            estate = await session.scalar(
                select(Estate).where(Estate.key == estate_key)
            )
            if estate is None:
                return None

            # Load all projects with components and repositories
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
        self,
        session: AsyncSession,
        catalogue_repos: dict[str, RepositoryRecord],
        estate_id: str | None,
        result: SyncResult,
    ) -> None:
        """Project catalogue repositories into Silver, updating or creating."""
        # Load existing Silver repositories scoped to this estate for deactivation.
        # We only deactivate repositories that belong to the current estate (or have
        # no estate_id), not repositories from other estates.
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
                # Update existing Silver repository
                silver_repo = silver_repos[slug]
                changed = self._update_silver_repository(
                    silver_repo, cat_repo, estate_id, now
                )
                if changed:
                    result.repositories_updated += 1
                continue

            # Create new Silver repository
            silver_repo = self._create_silver_repository(cat_repo, estate_id, now)
            session.add(silver_repo)
            result.repositories_created += 1

        # Deactivate repositories no longer in catalogue (only those in silver_repos,
        # which is already scoped to the current estate)
        self._deactivate_removed_repositories(silver_repos, seen_slugs, now, result)

    def _create_silver_repository(
        self,
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
        self,
        slug: str,
        silver_repo: Repository,
        seen_slugs: set[str],
    ) -> bool:
        """Determine whether a Silver repository should be deactivated.

        A repository should be deactivated if:
        - It's not in the current catalogue sync (not in seen_slugs)
        - It was previously synced from the catalogue (has catalogue_repository_id)
        - Ingestion is currently enabled
        """
        return (
            slug not in seen_slugs
            and silver_repo.catalogue_repository_id is not None
            and silver_repo.ingestion_enabled
        )

    def _deactivate_removed_repositories(
        self,
        silver_repos: dict[str, Repository],
        seen_slugs: set[str],
        now: dt.datetime,
        result: SyncResult,
    ) -> None:
        """Deactivate repositories that are no longer in the catalogue."""
        for slug, silver_repo in silver_repos.items():
            if self._should_deactivate_repository(slug, silver_repo, seen_slugs):
                silver_repo.ingestion_enabled = False
                silver_repo.last_synced_at = now
                result.repositories_deactivated += 1

    def _update_silver_repository(
        self,
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

        # Re-enable ingestion if repo is back in catalogue and was disabled
        if not silver_repo.ingestion_enabled and cat_repo.is_active:
            silver_repo.ingestion_enabled = True
            changed = True

        # Disable ingestion if repo is inactive in the catalogue
        if silver_repo.ingestion_enabled and not cat_repo.is_active:
            silver_repo.ingestion_enabled = False
            changed = True

        # Update documentation paths
        new_paths = list(cat_repo.documentation_paths)
        if silver_repo.documentation_paths != new_paths:
            silver_repo.documentation_paths = new_paths
            changed = True

        if changed:
            silver_repo.last_synced_at = now

        return changed

    async def _list_repositories(
        self,
        estate_id: str | None = None,
        *,
        ingestion_enabled: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[RepositoryInfo]:
        """List repositories with optional filters.

        Parameters
        ----------
        estate_id:
            Optional filter to limit results to a specific estate.
        ingestion_enabled:
            Optional filter for ingestion status. If None, return all repositories.
        limit:
            Optional maximum number of repositories to return.
        offset:
            Optional number of ordered rows to skip before returning results.

        Returns
        -------
        list[RepositoryInfo]
            Repository metadata matching the filters.

        """
        async with self._silver_sf() as session:
            query = select(Repository)

            if ingestion_enabled is not None:
                query = query.where(Repository.ingestion_enabled.is_(ingestion_enabled))

            if estate_id is not None:
                query = query.where(Repository.estate_id == estate_id)

            query = query.order_by(Repository.github_owner, Repository.github_name)

            if offset is not None:
                query = query.offset(offset)

            if limit is not None:
                query = query.limit(limit)

            repos = await session.scalars(query)
            return [self._to_repository_info(repo) for repo in repos]

    async def list_active_repositories(
        self,
        estate_id: str | None = None,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[RepositoryInfo]:
        """Return all repositories enabled for ingestion.

        Parameters
        ----------
        estate_id:
            Optional filter to limit results to a specific estate.
        limit:
            Optional maximum number of repositories to return.
        offset:
            Optional number of ordered rows to skip before returning results.

        Returns
        -------
        list[RepositoryInfo]
            Repository metadata needed by the ingestion worker.

        Notes
        -----
        For large deployments, prefer bounded queries by providing `limit`
        (and `offset` for pagination) rather than loading all repositories at
        once.

        """
        return await self._list_repositories(
            estate_id,
            ingestion_enabled=True,
            limit=limit,
            offset=offset,
        )

    async def list_all_repositories(
        self,
        estate_id: str | None = None,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[RepositoryInfo]:
        """Return all repositories regardless of ingestion status.

        Parameters
        ----------
        estate_id:
            Optional filter to limit results to a specific estate.
        limit:
            Optional maximum number of repositories to return.
        offset:
            Optional number of ordered rows to skip before returning results.

        Returns
        -------
        list[RepositoryInfo]
            Repository metadata for all repositories.

        Notes
        -----
        For large deployments, prefer bounded queries by providing `limit`
        (and `offset` for pagination) rather than loading all repositories at
        once.

        """
        return await self._list_repositories(
            estate_id,
            ingestion_enabled=None,
            limit=limit,
            offset=offset,
        )

    async def enable_ingestion(self, owner: str, name: str) -> bool:
        """Enable ingestion for a repository.

        Parameters
        ----------
        owner:
            GitHub repository owner.
        name:
            GitHub repository name.

        Returns
        -------
        bool
            True if the repository was found and updated.

        Raises
        ------
        RepositoryNotFoundError
            If the repository does not exist.

        """
        return await self._set_ingestion_enabled(owner, name, enabled=True)

    async def disable_ingestion(self, owner: str, name: str) -> bool:
        """Disable ingestion for a repository without deleting it.

        Parameters
        ----------
        owner:
            GitHub repository owner.
        name:
            GitHub repository name.

        Returns
        -------
        bool
            True if the repository was found and updated.

        Raises
        ------
        RepositoryNotFoundError
            If the repository does not exist.

        """
        return await self._set_ingestion_enabled(owner, name, enabled=False)

    async def _set_ingestion_enabled(
        self, owner: str, name: str, *, enabled: bool
    ) -> bool:
        """Set the ingestion_enabled flag for a repository."""
        async with self._silver_sf() as session, session.begin():
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == owner,
                    Repository.github_name == name,
                )
            )
            if repo is None:
                raise RepositoryNotFoundError(f"{owner}/{name}")

            if repo.ingestion_enabled == enabled:
                return False

            repo.ingestion_enabled = enabled
            return True

    async def get_repository_by_slug(self, slug: str) -> RepositoryInfo | None:
        """Look up a repository by owner/name slug.

        Parameters
        ----------
        slug:
            Repository slug in "owner/name" format.

        Returns
        -------
        RepositoryInfo | None
            Repository metadata if found, None otherwise.

        """
        if slug.count("/") != 1:
            return None

        owner, name = slug.split("/")
        async with self._silver_sf() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == owner,
                    Repository.github_name == name,
                )
            )
            return self._to_repository_info(repo) if repo else None

    def _to_repository_info(self, repo: Repository) -> RepositoryInfo:
        """Convert a Silver Repository to a RepositoryInfo DTO."""
        return RepositoryInfo(
            id=repo.id,
            owner=repo.github_owner,
            name=repo.github_name,
            default_branch=repo.default_branch,
            ingestion_enabled=repo.ingestion_enabled,
            documentation_paths=tuple(repo.documentation_paths),
            estate_id=repo.estate_id,
        )
