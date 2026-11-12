"""Unit tests for the Silver persistence statements used by registry sync."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest
from sqlalchemy import Insert
from sqlalchemy.dialects import postgresql, sqlite

from ghillie.catalogue import CatalogueImporter
from ghillie.registry import RepositoryRegistryService, storage
from ghillie.registry import sync as sync_module
from ghillie.silver.storage import Repository
from tests.unit.registry_service_sync_helpers import (
    catalogue_naming,
    fetch_silver_repo,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import Dialect
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _Dialect:
    """Minimal stand-in for a SQLAlchemy dialect."""

    def __init__(self, name: str) -> None:
        """Record the dialect name the strategies switch on."""
        self.name = name


class _Bind:
    """Minimal stand-in for an engine bind."""

    def __init__(self, name: str) -> None:
        """Expose a dialect under the attribute a bind provides."""
        self.dialect = _Dialect(name)


class _DialectSession:
    """Minimal stand-in exposing only the dialect the selector reads."""

    def __init__(self, name: str) -> None:
        """Wrap a fake bind for ``get_bind`` to return."""
        self._bind = _Bind(name)

    def get_bind(self) -> _Bind:
        """Return the fake bind the strategy inspects."""
        return self._bind


def _dialect_session(name: str) -> AsyncSession:
    """Return a stand-in carrying only the dialect a strategy reads.

    The strategies need nothing else from a session to build or decline a
    statement, so a full ``AsyncSession`` would add no coverage, only setup.
    The cast states that narrow contract once instead of at every call.
    """
    return typ.cast("AsyncSession", _DialectSession(name))


def _row(name: str = "wildside") -> Repository:
    """Build an unsaved Silver row for statement-shape tests."""
    return Repository(
        github_owner="leynos",
        github_name=name,
        default_branch="main",
        ingestion_enabled=True,
        documentation_paths=[],
    )


class _RecordingStrategy:
    """Record each insert the sync asks a strategy to build."""

    def __init__(self) -> None:
        """Start empty, delegating the statement to the dialect strategy."""
        self.built: list[str] = []
        self._delegate = storage.DialectUpsertStrategy()

    def build(self, session: AsyncSession, row: Repository) -> Insert | None:
        """Record the row then delegate to the dialect strategy."""
        self.built.append(row.slug)
        return self._delegate.build(session, row)


class _DecliningStrategy:
    """Decline every upsert, forcing the caller's plain-insert fallback."""

    def build(self, session: AsyncSession, row: Repository) -> Insert | None:
        """Return no statement, as an unsupported dialect would."""
        return None


@pytest.mark.parametrize(
    ("dialect_name", "expected"),
    [
        ("postgresql", storage.PostgresUpsertStrategy),
        ("sqlite", storage.SqliteUpsertStrategy),
        ("oracle", storage.PlainInsertStrategy),
    ],
)
def test_dialect_upsert_strategy_names_the_strategy_for_each_dialect(
    dialect_name: str,
    expected: type[object],
) -> None:
    """Each known dialect resolves to its named strategy; the rest fall back."""
    assert isinstance(storage.dialect_upsert_strategy(dialect_name), expected)


def test_the_plain_strategy_declines_the_upsert() -> None:
    """The fallback returns no statement so the caller inserts plainly."""
    assert (
        storage.PlainInsertStrategy().build(_dialect_session("oracle"), _row()) is None
    )


@pytest.mark.parametrize(
    ("dialect_name", "compile_dialect"),
    [("postgresql", postgresql.dialect()), ("sqlite", sqlite.dialect())],
)
def test_supported_dialects_build_an_insert_that_ignores_a_conflict(
    dialect_name: str,
    compile_dialect: Dialect,
) -> None:
    """A supported dialect builds the ON CONFLICT DO NOTHING insert."""
    statement = storage.dialect_upsert_strategy(dialect_name).build(
        _dialect_session(dialect_name), _row()
    )
    assert isinstance(statement, Insert), "The strategy should build an insert"
    compiled = str(statement.compile(dialect=compile_dialect))
    assert "ON CONFLICT DO NOTHING" in compiled.upper(), (
        "The insert must leave a conflicting row untouched"
    )


def test_the_dialect_strategy_resolves_from_the_session() -> None:
    """The default strategy picks the named strategy from the session dialect."""
    strategy = storage.DialectUpsertStrategy()
    assert isinstance(strategy.build(_dialect_session("sqlite"), _row()), Insert), (
        "SQLite should build an upsert"
    )
    assert strategy.build(_dialect_session("oracle"), _row()) is None, (
        "An unknown dialect should decline rather than raise"
    )


@pytest.mark.asyncio
async def test_insert_ignoring_duplicates_reports_which_sync_inserted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The statement reports insertion instead of raising on a conflict."""
    async with session_factory() as session, session.begin():
        strategy = storage.DialectUpsertStrategy()
        first = await storage.insert_ignoring_duplicates(
            session, _row("first"), strategy
        )
        duplicate = await storage.insert_ignoring_duplicates(
            session, _row("first"), strategy
        )
        declined = await storage.insert_ignoring_duplicates(
            session, _row("second"), _DecliningStrategy()
        )
    assert first is storage.InsertOutcome.INSERTED, "The first insert should land"
    assert duplicate is storage.InsertOutcome.CONFLICT, (
        "The conflicting insert should report the existing row"
    )
    assert declined is storage.InsertOutcome.DECLINED, (
        "A strategy without an upsert should decline, not claim a conflict"
    )


@pytest.mark.asyncio
async def test_sync_uses_the_injected_upsert_strategy(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A substituted strategy is the one the sync builds its inserts with."""
    catalogue = tmp_path / "catalogue.yaml"
    catalogue.write_text(catalogue_naming(("wildside",)), encoding="utf-8")
    importer = CatalogueImporter(session_factory, estate_key="test")
    await importer.import_path(catalogue, commit_sha="injected-strategy")
    recorder = _RecordingStrategy()

    result = await sync_module.sync_from_catalogue(
        session_factory,
        session_factory,
        "test",
        upsert_strategy=recorder,
    )

    assert result.repositories_created == 1, "The sync should create one row"
    assert recorder.built == ["leynos/wildside"], (
        "The sync must ask the injected strategy to build the insert"
    )


@pytest.mark.asyncio
async def test_the_service_passes_its_upsert_strategy_to_the_sync(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """The composition edge can choose the strategy for every sync it runs."""
    catalogue = tmp_path / "catalogue.yaml"
    catalogue.write_text(catalogue_naming(("wildside",)), encoding="utf-8")
    importer = CatalogueImporter(session_factory, estate_key="test")
    await importer.import_path(catalogue, commit_sha="service-strategy")
    recorder = _RecordingStrategy()

    service = RepositoryRegistryService(
        session_factory, session_factory, upsert_strategy=recorder
    )
    result = await service.sync_from_catalogue("test")

    assert result.repositories_created == 1, "The sync should create one row"
    assert recorder.built == ["leynos/wildside"], (
        "The service must hand its strategy to the sync it runs"
    )


@pytest.mark.asyncio
async def test_a_declining_strategy_falls_back_to_the_plain_insert(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A strategy that declines still lets the sync insert through the session."""
    catalogue = tmp_path / "catalogue.yaml"
    catalogue.write_text(catalogue_naming(("wildside",)), encoding="utf-8")
    importer = CatalogueImporter(session_factory, estate_key="test")
    await importer.import_path(catalogue, commit_sha="declining-strategy")

    result = await sync_module.sync_from_catalogue(
        session_factory,
        session_factory,
        "test",
        upsert_strategy=_DecliningStrategy(),
    )

    assert result.repositories_created == 1, "The plain insert should still create"
    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None, "The fallback should persist the row"


@pytest.mark.asyncio
async def test_sync_uses_the_injected_clock(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """The sync stamps rows with the injected clock instead of patching time."""
    fixed = dt.datetime(2030, 1, 2, 3, 4, 5, tzinfo=dt.UTC)
    catalogue = tmp_path / "catalogue.yaml"
    catalogue.write_text(catalogue_naming(("wildside",)), encoding="utf-8")
    importer = CatalogueImporter(session_factory, estate_key="test")
    await importer.import_path(catalogue, commit_sha="injected-clock")

    await sync_module.sync_from_catalogue(
        session_factory,
        session_factory,
        "test",
        now=lambda: fixed,
    )

    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None, "The sync should create the row"
    assert repo.last_synced_at == fixed, "The row should carry the injected time"
