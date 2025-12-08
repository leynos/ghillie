"""Shared fixtures for unit and feature tests."""

from __future__ import annotations

import contextlib
import logging
import os
import socket
import typing as typ

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ghillie.bronze import init_bronze_storage
from ghillie.gold import init_gold_storage
from ghillie.silver import init_silver_storage

if typ.TYPE_CHECKING:
    from pathlib import Path

try:
    from py_pglite import PGliteConfig, PGliteManager

    _PGLITE_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    _PGLITE_AVAILABLE = False

logger = logging.getLogger(__name__)


def _should_use_pglite() -> bool:
    """Return True when tests should run against py-pglite Postgres."""
    target = os.getenv("GHILLIE_TEST_DB", "pglite").lower()
    return target != "sqlite" and _PGLITE_AVAILABLE


def _find_free_port() -> int:
    """Find an available TCP port for a temporary Postgres instance."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.asynccontextmanager
async def _pglite_engine(tmp_path: Path) -> typ.AsyncIterator[AsyncEngine]:
    """Start a py-pglite Postgres and yield an async engine bound to it."""
    port = _find_free_port()
    work_dir = tmp_path / "pglite"
    config = PGliteConfig(
        use_tcp=True, tcp_host="127.0.0.1", tcp_port=port, work_dir=work_dir
    )

    with PGliteManager(config):
        url = (
            f"postgresql+asyncpg://postgres:postgres@{config.tcp_host}:"
            f"{config.tcp_port}/postgres"
        )
        engine = create_async_engine(url)
        try:
            yield engine
        finally:
            await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    tmp_path: Path,
) -> typ.AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a fresh async session factory backed by sqlite."""
    engine_cm = None
    engine = None
    if _should_use_pglite():
        try:
            engine_cm = _pglite_engine(tmp_path)
            engine = await engine_cm.__aenter__()
            await init_bronze_storage(engine)
            await init_silver_storage(engine)
            await init_gold_storage(engine)
        except Exception as exc:  # noqa: BLE001
            # pragma: no cover - fall back when py-pglite fails at any stage
            logger.warning("py-pglite unavailable, falling back to SQLite: %s", exc)
            if engine_cm is not None:
                with contextlib.suppress(Exception):
                    await engine_cm.__aexit__(None, None, None)
            engine_cm = None
            engine = None

    if engine is None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bronze.db'}")
        try:
            await init_bronze_storage(engine)
            await init_silver_storage(engine)
            await init_gold_storage(engine)
        except Exception:
            await engine.dispose()
            raise

    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        if engine_cm is not None:
            await engine_cm.__aexit__(None, None, None)
