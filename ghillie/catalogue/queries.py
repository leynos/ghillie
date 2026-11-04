"""Read queries over the catalogue tables for estate management.

These queries live in the catalogue package because estates and their import
history are catalogue-owned records. The estate service imports them through the
``outbound_adapter`` group.
"""

import dataclasses
import typing as typ

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ghillie.catalogue.storage import CatalogueImportRecord, Estate

if typ.TYPE_CHECKING:
    import datetime as dt

    from sqlalchemy.sql.selectable import Subquery

type SessionFactory = async_sessionmaker[AsyncSession]


@dataclasses.dataclass(frozen=True, slots=True)
class EstateRow:
    """An estate together with its most recent catalogue import."""

    id: str
    key: str
    name: str
    description: str | None
    last_import_commit_sha: str | None
    last_imported_at: dt.datetime | None


def _latest_import_subquery(estate_key: str | None = None) -> Subquery:
    """Rank imports per estate so the outer join can pick rank one.

    Parameters
    ----------
    estate_key:
        When supplied, rank only this estate's imports. The single-estate
        lookup uses it so PostgreSQL does not scan the whole import history
        for a window whose other ranks the outer filter would discard anyway.

    """
    query = select(
        CatalogueImportRecord.estate_id.label("estate_id"),
        CatalogueImportRecord.commit_sha.label("commit_sha"),
        CatalogueImportRecord.imported_at.label("imported_at"),
        func.row_number()
        .over(
            partition_by=CatalogueImportRecord.estate_id,
            order_by=[
                CatalogueImportRecord.imported_at.desc(),
                CatalogueImportRecord.id.desc(),
            ],
        )
        .label("rank"),
    )
    if estate_key is not None:
        query = query.join(Estate, Estate.id == CatalogueImportRecord.estate_id).where(
            Estate.key == estate_key
        )
    return query.subquery()


async def list_estates(
    session_factory: SessionFactory,
    *,
    limit: int,
    offset: int,
) -> list[EstateRow]:
    """Return estates ordered by key, each with its latest import.

    Parameters
    ----------
    session_factory:
        Factory for async catalogue sessions.
    limit:
        Maximum number of rows to return.
    offset:
        Number of ordered rows to skip.

    Returns
    -------
    list[EstateRow]
        Estates in key order.

    """
    latest = _latest_import_subquery()
    query = (
        select(Estate, latest.c.commit_sha, latest.c.imported_at)
        .outerjoin(
            latest,
            and_(latest.c.estate_id == Estate.id, latest.c.rank == 1),
        )
        .order_by(Estate.key)
        .offset(offset)
        .limit(limit)
    )

    async with session_factory() as session:
        rows = (await session.execute(query)).all()

    return [
        EstateRow(
            id=estate.id,
            key=estate.key,
            name=estate.name,
            description=estate.description,
            last_import_commit_sha=commit_sha,
            last_imported_at=imported_at,
        )
        for estate, commit_sha, imported_at in rows
    ]


async def get_estate_by_key(
    session_factory: SessionFactory, key: str
) -> EstateRow | None:
    """Return one estate by key, with its latest import, or ``None``."""
    latest = _latest_import_subquery(key)
    query = (
        select(Estate, latest.c.commit_sha, latest.c.imported_at)
        .outerjoin(
            latest,
            and_(latest.c.estate_id == Estate.id, latest.c.rank == 1),
        )
        .where(Estate.key == key)
    )

    async with session_factory() as session:
        row = (await session.execute(query)).first()

    if row is None:
        return None

    estate, commit_sha, imported_at = row
    return EstateRow(
        id=estate.id,
        key=estate.key,
        name=estate.name,
        description=estate.description,
        last_import_commit_sha=commit_sha,
        last_imported_at=imported_at,
    )
