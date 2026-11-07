"""Shared lookups for the registry service sync tests."""

from __future__ import annotations

import typing as typ

from sqlalchemy import select

from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SilverSnapshot = list[tuple[object, ...]]


async def fetch_silver_repo(
    session_factory: async_sessionmaker[AsyncSession],
    owner: str,
    name: str,
) -> Repository | None:
    """Fetch a repository from Silver by owner/name."""
    async with session_factory() as session:
        return await session.scalar(
            select(Repository).where(
                Repository.github_owner == owner,
                Repository.github_name == name,
            )
        )


def _repository_fields(repo: Repository) -> tuple[object, ...]:
    """Return every mutable field of a Silver row as a comparable tuple."""
    return (
        repo.id,
        repo.github_owner,
        repo.github_name,
        repo.default_branch,
        repo.estate_id,
        repo.catalogue_repository_id,
        repo.ingestion_enabled,
        repo.last_synced_at,
        tuple(repo.documentation_paths),
        repo.is_active,
        repo.created_at,
        repo.updated_at,
    )


async def snapshot_silver_repos(
    session_factory: async_sessionmaker[AsyncSession],
) -> SilverSnapshot:
    """Snapshot every Silver repository so a test can prove none changed.

    The snapshot is taken inside the session: ORM instances are expired when a
    session closes, so reading their attributes afterwards would be unreliable.
    Rows are ordered by owner and name to keep the comparison deterministic.
    """
    async with session_factory() as session:
        repositories = (
            await session.scalars(
                select(Repository).order_by(
                    Repository.github_owner, Repository.github_name
                )
            )
        ).all()
        return [_repository_fields(repo) for repo in repositories]


async def snapshot_silver_repo(
    session_factory: async_sessionmaker[AsyncSession],
    owner: str,
    name: str,
) -> tuple[object, ...] | None:
    """Snapshot one Silver row so a test can prove it did not change."""
    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == owner,
                Repository.github_name == name,
            )
        )
        return None if repo is None else _repository_fields(repo)
