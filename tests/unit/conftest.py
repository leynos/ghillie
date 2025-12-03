"""Shared fixtures for unit tests."""

from __future__ import annotations

import asyncio
import typing as typ

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ghillie.bronze import init_bronze_storage
from ghillie.silver import init_silver_storage

if typ.TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def session_factory(
    tmp_path: Path,
) -> typ.Iterator[async_sessionmaker[AsyncSession]]:
    """Yield a fresh async session factory backed by sqlite."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bronze.db'}")
    asyncio.run(init_bronze_storage(engine))
    asyncio.run(init_silver_storage(engine))

    yield async_sessionmaker(engine, expire_on_commit=False)

    asyncio.run(engine.dispose())
