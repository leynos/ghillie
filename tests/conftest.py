"""Shared fixtures for unit and feature tests."""

from __future__ import annotations

import typing as typ

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ghillie.bronze import init_bronze_storage
from ghillie.silver import init_silver_storage

if typ.TYPE_CHECKING:
    from pathlib import Path


@pytest_asyncio.fixture
async def session_factory(
    tmp_path: Path,
) -> typ.AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a fresh async session factory backed by sqlite."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bronze.db'}")
    await init_bronze_storage(engine)
    await init_silver_storage(engine)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
