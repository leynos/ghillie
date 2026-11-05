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
    import collections.abc as cabc
    import datetime as dt

    from sqlalchemy.sql.selectable import Subquery

type SessionFactory = async_sessionmaker[AsyncSession]


@dataclasses.dataclass(frozen=True, slots=True)
class EstateRow:
    """An estate together with its most recent catalogue import.

    Attributes
    ----------
    id:
        Database identifier used to key the row's repository projections.
    key:
        Operator-facing estate key.
    name:
        Display name of the estate.
    description:
        Optional operator description, or ``None``.
    last_import_commit_sha:
        Commit of the latest catalogue import, or ``None`` if never imported.
    last_imported_at:
        Time of the latest catalogue import, or ``None`` if never imported.

    """

    id: str
    key: str
    name: str
    description: str | None
    last_import_commit_sha: str | None
    last_imported_at: dt.datetime | None


def _latest_import_subquery(
    estate_key: str | None = None,
    *,
    estate_ids: cabc.Sequence[str] | None = None,
) -> Subquery:
    """Rank imports per estate so the outer join can pick rank one.

    Parameters
    ----------
    estate_key:
        When supplied, rank only this estate's imports. The single-estate
        lookup uses it so PostgreSQL does not scan the whole import history
        for a window whose other ranks the outer filter would discard anyway.
    estate_ids:
        When supplied, rank only these estates' imports. The paged listing
        uses it after selecting its page, so the window never spans the whole
        import history.

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
    elif estate_ids is not None:
        query = query.where(CatalogueImportRecord.estate_id.in_(estate_ids))
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
    async with session_factory() as session:
        # Select the page first so the ranking window only covers the estates
        # it will return instead of the whole import history.
        estates = (
            (
                await session.execute(
                    select(Estate).order_by(Estate.key).offset(offset).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        if not estates:
            return []

        latest = _latest_import_subquery(estate_ids=[estate.id for estate in estates])
        imports = (
            await session.execute(
                select(
                    latest.c.estate_id,
                    latest.c.commit_sha,
                    latest.c.imported_at,
                ).where(latest.c.rank == 1)
            )
        ).all()

        # Build the rows before the session closes so every attribute is read
        # while the ORM instances are still attached and loaded.
        by_estate = {
            estate_id: (commit_sha, imported_at)
            for estate_id, commit_sha, imported_at in imports
        }
        rows: list[EstateRow] = []
        for estate in estates:
            commit_sha, imported_at = by_estate.get(estate.id, (None, None))
            rows.append(
                EstateRow(
                    id=estate.id,
                    key=estate.key,
                    name=estate.name,
                    description=estate.description,
                    last_import_commit_sha=commit_sha,
                    last_imported_at=imported_at,
                )
            )
        return rows


async def get_estate_by_key(
    session_factory: SessionFactory, key: str
) -> EstateRow | None:
    """Return one estate by key, with its latest import, or ``None``.

    Parameters
    ----------
    session_factory:
        Factory for async catalogue sessions.
    key:
        Estate key to look up.

    Returns
    -------
    EstateRow | None
        The matching estate, or ``None`` when no estate has that key.

    """
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
