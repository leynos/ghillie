"""Opt-in schema bootstrap (D13).

``init_all_storage`` must create every table the runtime needs on an empty
database and must be safe to run repeatedly, because every replica runs it at
start-up when ``GHILLIE_DB_BOOTSTRAP=create-all``.
"""

import typing as typ

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

_EXPECTED_TABLES = {
    # Bronze
    "raw_events",
    "commits",
    "issues",
    "pull_requests",
    "documentation_changes",
    "event_facts",
    "github_ingestion_offsets",
    # Silver
    "repositories",
    "components",
    "component_edges",
    # Gold
    "reports",
    "report_reviews",
    "report_projects",
    "report_coverage",
    # Catalogue
    "estates",
    "catalogue_imports",
    "projects",
    "catalogue_repositories",
}


async def _table_names(engine: AsyncEngine) -> set[str]:
    """Return the table names the engine's database holds."""
    async with engine.connect() as connection:
        names = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names()
        )
    return set(names)


@pytest_asyncio.fixture
async def engine(tmp_path: Path) -> cabc.AsyncIterator[AsyncEngine]:
    """Yield a fresh SQLite engine, and dispose of it whatever the test does.

    ``tmp_path`` is per test, so each test still starts from its own empty
    database; only the create/dispose bookkeeping is shared.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bootstrap.db'}")
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_init_all_storage_creates_every_table(engine: AsyncEngine) -> None:
    """An empty SQLite database gains every layer's tables."""
    from ghillie.storage_bootstrap import init_all_storage

    await init_all_storage(engine)

    assert await _table_names(engine) >= _EXPECTED_TABLES, (
        "bootstrap should create every layer's tables"
    )


@pytest.mark.asyncio
async def test_init_all_storage_is_idempotent(engine: AsyncEngine) -> None:
    """Running the bootstrap twice succeeds and leaves existing data intact."""
    from ghillie.storage_bootstrap import init_all_storage

    await init_all_storage(engine)
    first = await _table_names(engine)

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO estates (id, key, name, description, "
                "created_at, updated_at) VALUES "
                "('estate-1', 'demo', 'Demo', NULL, "
                "'2024-01-01 00:00:00', '2024-01-01 00:00:00')"
            )
        )

    await init_all_storage(engine)

    assert await _table_names(engine) == first, (
        "a second bootstrap should not change the schema"
    )
    async with engine.connect() as connection:
        keys = (await connection.execute(text("SELECT key FROM estates"))).all()
    assert keys == [("demo",)], "a second bootstrap should preserve data"
