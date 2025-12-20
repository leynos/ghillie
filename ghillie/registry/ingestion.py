"""Ingestion toggles and repository lookups."""

from __future__ import annotations

import typing as typ

from sqlalchemy import select

from ghillie.common.slug import parse_repo_slug
from ghillie.registry.errors import RepositoryNotFoundError
from ghillie.registry.mapping import to_repository_info
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.registry.models import RepositoryInfo

    type SessionFactory = async_sessionmaker[AsyncSession]


async def set_ingestion_enabled(
    session_factory: SessionFactory,
    owner: str,
    name: str,
    *,
    enabled: bool,
) -> bool:
    """Set the ingestion_enabled flag for a repository.

    Parameters
    ----------
    session_factory
        Factory for creating async database sessions.
    owner
        GitHub repository owner.
    name
        GitHub repository name.
    enabled
        Desired ingestion-enabled state.

    Returns
    -------
    bool
        True if the flag changed, False if no update was needed.

    Raises
    ------
    RepositoryNotFoundError
        If the repository does not exist.

    """
    async with session_factory() as session, session.begin():
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == owner,
                Repository.github_name == name,
            )
        )
        if repo is None:
            slug = f"{owner}/{name}"
            raise RepositoryNotFoundError(slug)

        if repo.ingestion_enabled == enabled:
            return False

        repo.ingestion_enabled = enabled
        return True


async def get_repository_by_slug(
    session_factory: SessionFactory, slug: str
) -> RepositoryInfo | None:
    """Look up a repository by owner/name slug.

    Parameters
    ----------
    session_factory
        Factory for creating async database sessions.
    slug
        Repository slug in "owner/name" format.

    Returns
    -------
    RepositoryInfo | None
        Repository metadata if found, otherwise None.

    """
    try:
        owner, name = parse_repo_slug(slug)
    except ValueError:
        return None

    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == owner,
                Repository.github_name == name,
            )
        )
        return to_repository_info(repo) if repo else None
