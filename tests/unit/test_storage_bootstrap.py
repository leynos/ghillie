"""Opt-in schema bootstrap (D13).

``init_all_storage`` must create every table the runtime needs on an empty
database and must be safe to run repeatedly, because every replica runs it at
start-up when ``GHILLIE_DB_BOOTSTRAP=create-all``.
"""

import typing as typ

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

if typ.TYPE_CHECKING:
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
    async with engine.connect() as connection:
        names = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names()
        )
    return set(names)


@pytest.mark.asyncio
async def test_init_all_storage_creates_every_table(tmp_path: Path) -> None:
    """An empty SQLite database gains every layer's tables."""
    from ghillie.storage_bootstrap import init_all_storage

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bootstrap.db'}")
    try:
        await init_all_storage(engine)

        assert await _table_names(engine) >= _EXPECTED_TABLES, (
            "bootstrap should create every layer's tables"
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_init_all_storage_is_idempotent(tmp_path: Path) -> None:
    """Running the bootstrap twice succeeds and leaves the schema intact."""
    from ghillie.storage_bootstrap import init_all_storage

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'twice.db'}")
    try:
        await init_all_storage(engine)
        first = await _table_names(engine)

        await init_all_storage(engine)

        assert await _table_names(engine) == first, (
            "a second bootstrap should not change the schema"
        )
    finally:
        await engine.dispose()
