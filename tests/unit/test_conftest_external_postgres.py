"""Guard tests for the external-Postgres test fixture."""

from __future__ import annotations

import asyncio
import os
import typing as typ

import pytest
from sqlalchemy import text

from tests import conftest

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

_UNREACHABLE_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:1/ghillie_test"

# A table that no storage layer creates, so its absence after setup proves the
# reset dropped pre-existing state rather than merely adding tables.
_RESET_PROBE_TABLE = "reset_probe"


async def _seed_reset_probe(url: str) -> None:
    """Create the marker table the reset must remove."""
    engine = conftest.create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(f"CREATE TABLE {_RESET_PROBE_TABLE} (id integer)")
            )
    finally:
        await engine.dispose()


async def _public_tables(engine: AsyncEngine) -> set[str]:
    """Read the public table names without changing them."""
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        )
        return {str(row[0]) for row in rows}


async def _exercise_serial_setup(url: str) -> set[str]:
    """Seed a marker, run the fixture's setup, and return the tables it leaves."""
    await _seed_reset_probe(url)
    engine = await conftest._setup_external_postgres(url)
    try:
        return await _public_tables(engine)
    finally:
        await engine.dispose()


def test_external_postgres_setup_raises_under_xdist_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fixture refuses a shared schema before it opens any connection.

    The URL points at a closed port, so reaching the engine at all would fail
    with a connection error rather than the guard's diagnostic.
    """
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    created: list[tuple[object, ...]] = []

    def _record_engine(*args: object, **kwargs: object) -> object:
        """Record any engine construction, which the guard must never reach."""
        created.append(args)
        return object()

    monkeypatch.setattr(conftest, "create_async_engine", _record_engine)

    with pytest.raises(conftest.ExternalPostgresUnderXdistError):
        asyncio.run(conftest._setup_external_postgres(_UNREACHABLE_URL))

    assert created == [], "The guard must raise before any engine is created"


@pytest.mark.skipif(
    conftest._external_postgres_url() is None,
    reason="needs GHILLIE_TEST_DB pointing at a disposable Postgres",
)
@pytest.mark.skipif(
    os.getenv("PYTEST_XDIST_WORKER") is not None,
    reason="the external Postgres fixture resets a shared schema; run serially",
)
def test_external_postgres_setup_works_serially() -> None:
    """A serial run drops seeded state and initializes both storages."""
    url = conftest._external_postgres_url()
    assert url is not None, "The skip guard guarantees a URL"

    tables = asyncio.run(_exercise_serial_setup(url))

    assert _RESET_PROBE_TABLE not in tables, (
        "Setup must drop the schema, removing the seeded marker table"
    )
    assert {"estates", "repositories"} <= tables, (
        "Setup must initialize the catalogue and Silver storage tables"
    )
