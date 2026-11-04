"""Catalogue-owned read queries used by the estate service."""

import dataclasses
import datetime as dt
import typing as typ

import pytest
from sqlalchemy import select

from ghillie.catalogue.queries import (
    EstateRow,
    _latest_import_subquery,
    get_estate_by_key,
    list_estates,
)
from ghillie.catalogue.storage import CatalogueImportRecord, Estate

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _add_estate(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    key: str,
    name: str | None = None,
    description: str | None = None,
) -> Estate:
    """Insert one estate and return the persisted row."""
    async with session_factory() as session, session.begin():
        estate = Estate(key=key, name=name or key.title(), description=description)
        session.add(estate)
    return estate


async def _add_import(
    session_factory: async_sessionmaker[AsyncSession],
    estate: Estate,
    *,
    commit_sha: str,
    imported_at: dt.datetime,
) -> None:
    """Record one catalogue import for *estate*."""
    async with session_factory() as session, session.begin():
        session.add(
            CatalogueImportRecord(
                estate_id=estate.id,
                commit_sha=commit_sha,
                imported_at=imported_at,
            )
        )


@pytest.mark.asyncio
async def test_list_estates_is_empty_initially(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An empty database lists no estates."""
    assert await list_estates(session_factory, limit=10, offset=0) == [], (
        "an empty database should list no estates"
    )


@pytest.mark.asyncio
async def test_list_estates_orders_by_key_and_pages(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Estates are ordered by key and the offset is applied after ordering."""
    for key in ("gamma", "alpha", "beta"):
        await _add_estate(session_factory, key=key)

    page = await list_estates(session_factory, limit=2, offset=1)

    assert [row.key for row in page] == ["beta", "gamma"], "offset follows key order"


@pytest.mark.asyncio
async def test_list_estates_includes_the_latest_import(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Each row carries the most recent import, not an arbitrary one."""
    estate = await _add_estate(session_factory, key="alpha", name="Alpha")
    await _add_import(
        session_factory,
        estate,
        commit_sha="older",
        imported_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    await _add_import(
        session_factory,
        estate,
        commit_sha="newer",
        imported_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
    )

    [row] = await list_estates(session_factory, limit=10, offset=0)

    assert row.key == "alpha", "row should carry the estate key"
    assert row.name == "Alpha", "row should carry the estate name"
    assert row.last_import_commit_sha == "newer", "row should carry the newest commit"
    assert row.last_imported_at is not None, "latest import timestamp should be present"
    # SQLite drops tzinfo; compare the wall-clock value so both backends agree.
    assert row.last_imported_at.replace(tzinfo=None) == dt.datetime(  # noqa: DTZ001 - compares wall-clock values.
        2026, 2, 1
    ), "latest import should use the newest timestamp"


@pytest.mark.asyncio
async def test_list_estates_keeps_estates_without_imports(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An estate with no import still appears, with a null import."""
    await _add_estate(session_factory, key="alpha", description="Demo estate")

    [row] = await list_estates(session_factory, limit=10, offset=0)

    assert row.description == "Demo estate", "row should carry the estate description"
    assert row.last_import_commit_sha is None, "no commit without an import"
    assert row.last_imported_at is None, "no timestamp without an import"


@pytest.mark.asyncio
async def test_get_estate_by_key_returns_the_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A known key resolves to its estate and latest import."""
    estate = await _add_estate(session_factory, key="alpha", name="Alpha")
    await _add_import(
        session_factory,
        estate,
        commit_sha="abc123",
        imported_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
    )

    row = await get_estate_by_key(session_factory, "alpha")

    assert row is not None, "known key should resolve to a row"
    assert row.id == estate.id, "row should carry the estate id"
    assert row.name == "Alpha", "row should carry the estate name"
    assert row.last_import_commit_sha == "abc123", "row should carry the newest commit"


@pytest.mark.asyncio
async def test_latest_import_subquery_scopes_to_one_estate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Scoping the ranking subquery keeps unrelated import history out."""
    alpha = await _add_estate(session_factory, key="alpha")
    beta = await _add_estate(session_factory, key="beta")
    await _add_import(
        session_factory,
        alpha,
        commit_sha="alpha-1",
        imported_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    await _add_import(
        session_factory,
        beta,
        commit_sha="beta-1",
        imported_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
    )

    subquery = _latest_import_subquery("alpha")
    async with session_factory() as session:
        rows = (await session.execute(select(subquery.c.commit_sha))).all()

    assert [row.commit_sha for row in rows] == ["alpha-1"], (
        "subquery should rank only the requested estate"
    )


@pytest.mark.asyncio
async def test_latest_import_subquery_scopes_to_estate_ids(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The paged listing ranks imports only for the estates it selected."""
    alpha = await _add_estate(session_factory, key="alpha")
    beta = await _add_estate(session_factory, key="beta")
    await _add_import(
        session_factory,
        alpha,
        commit_sha="alpha-1",
        imported_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    await _add_import(
        session_factory,
        beta,
        commit_sha="beta-1",
        imported_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
    )

    subquery = _latest_import_subquery(estate_ids=[alpha.id])
    async with session_factory() as session:
        rows = (await session.execute(select(subquery.c.commit_sha))).all()

    assert [row.commit_sha for row in rows] == ["alpha-1"], (
        "subquery should rank only the selected estates"
    )


@pytest.mark.asyncio
async def test_get_estate_by_key_returns_none_for_unknown_keys(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An unknown key resolves to ``None``."""
    assert await get_estate_by_key(session_factory, "missing") is None, (
        "unknown key should resolve to nothing"
    )


def test_estate_row_is_immutable() -> None:
    """Query rows cannot be mistaken for mutable ORM state."""
    row = EstateRow(
        id="1",
        key="alpha",
        name="Alpha",
        description=None,
        last_import_commit_sha=None,
        last_imported_at=None,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        row.key = "beta"  # ty: ignore[invalid-assignment]
