"""Repository registry service for managing GitHub ingestion targets.

The registry service bridges the catalogue domain (source of truth for estate
configuration) with the Silver layer (operational data store for ingestion
and reporting).
"""

from __future__ import annotations

import typing as typ

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ghillie.registry.ingestion import get_repository_by_slug, set_ingestion_enabled
from ghillie.registry.listing import RepositoryListOptions, list_repositories
from ghillie.registry.sync import sync_from_catalogue

if typ.TYPE_CHECKING:
    from ghillie.registry.models import RepositoryInfo, SyncResult

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
        """Synchronize all catalogue repositories to Silver for an estate.

        Reads repositories from the catalogue database (via component
        definitions) and projects them into the Silver repository table.
        Repositories no longer in the catalogue have ingestion disabled
        but are not deleted to preserve historical data.

        Parameters
        ----------
        estate_key:
            The estate whose repositories should be synchronized.

        Returns
        -------
        SyncResult
            Summary of created, updated, and deactivated repositories.

        Raises
        ------
        RegistrySyncError:
            If the estate cannot be found or sync fails.

        """
        return await sync_from_catalogue(
            self._catalogue_sf, self._silver_sf, estate_key
        )

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
        return await list_repositories(
            self._silver_sf,
            RepositoryListOptions(
                estate_id=estate_id,
                ingestion_enabled=True,
                limit=limit,
                offset=offset,
            ),
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
        return await list_repositories(
            self._silver_sf,
            RepositoryListOptions(
                estate_id=estate_id,
                ingestion_enabled=None,
                limit=limit,
                offset=offset,
            ),
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
        return await set_ingestion_enabled(self._silver_sf, owner, name, enabled=True)

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
        return await set_ingestion_enabled(self._silver_sf, owner, name, enabled=False)

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
        return await get_repository_by_slug(self._silver_sf, slug)
