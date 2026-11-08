"""Guard tests for the external-Postgres test fixture."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from tests import conftest

_UNREACHABLE_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:1/ghillie_test"


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
def test_external_postgres_setup_works_serially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A serial run resets the schema and initialises storage."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    url = conftest._external_postgres_url()
    assert url is not None, "The skip guard guarantees a URL"

    async def _public_table_count() -> int:
        engine = await conftest._setup_external_postgres(url)
        try:
            async with engine.connect() as connection:
                count = await connection.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
        finally:
            await engine.dispose()
        return int(count or 0)

    assert asyncio.run(_public_table_count()) > 0, (
        "Serial setup must leave the storage tables in place"
    )
