"""Repository listing/query helpers."""

from __future__ import annotations

import dataclasses
import typing as typ

from sqlalchemy import Select, select

from ghillie.registry.mapping import to_repository_info
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.registry.models import RepositoryInfo

    type SessionFactory = async_sessionmaker[AsyncSession]


class NegativePaginationError(ValueError):
    """Raised when pagination parameters are negative."""

    def __init__(self, name: str) -> None:
        """Build a consistent error message for the invalid parameter."""
        super().__init__(f"{name} must be non-negative")


@dataclasses.dataclass(frozen=True, slots=True)
class RepositoryListOptions:
    """Repository listing options."""

    estate_id: str | None = None
    ingestion_enabled: bool | None = None
    limit: int | None = None
    offset: int | None = None


def _validate_pagination(options: RepositoryListOptions) -> None:
    """Validate pagination parameters.

    Raises
    ------
    NegativePaginationError
        If limit or offset is negative.

    """
    if options.limit is not None and options.limit < 0:
        raise NegativePaginationError("limit")

    if options.offset is not None and options.offset < 0:
        raise NegativePaginationError("offset")


def _build_query(options: RepositoryListOptions) -> Select:
    """Build repository query with filters, ordering, and pagination.

    Parameters
    ----------
    options
        Filtering and pagination options.

    Returns
    -------
    Select
        SQLAlchemy select statement with applied filters and pagination.

    """
    query = select(Repository)

    if options.ingestion_enabled is not None:
        query = query.where(Repository.ingestion_enabled == options.ingestion_enabled)

    if options.estate_id is not None:
        query = query.where(Repository.estate_id == options.estate_id)

    query = query.order_by(Repository.github_owner, Repository.github_name)

    if options.offset is not None:
        query = query.offset(options.offset)

    if options.limit is not None:
        query = query.limit(options.limit)

    return query


async def list_repositories(
    session_factory: SessionFactory,
    options: RepositoryListOptions,
) -> list[RepositoryInfo]:
    """List repositories with optional filters.

    Parameters
    ----------
    session_factory
        Factory for creating async database sessions.
    options
        Filtering and pagination options.

    Returns
    -------
    list[RepositoryInfo]
        Repository information matching the filters.

    Raises
    ------
    NegativePaginationError
        If limit or offset is negative.

    """
    _validate_pagination(options)
    query = _build_query(options)

    async with session_factory() as session:
        repos = await session.scalars(query)
        return [to_repository_info(repo) for repo in repos]
