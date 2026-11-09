"""Dry-run and preview tests for RepositoryRegistryService catalogue syncing."""

from __future__ import annotations

import contextlib
import dataclasses
import typing as typ

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ghillie.catalogue import CatalogueImporter, Estate, RepositoryRecord
from ghillie.registry import RegistrySyncError, RepositoryRegistryService
from ghillie.registry.models import LEFT_DISABLED_PREVIEW_LIMIT
from ghillie.silver.storage import Repository
from tests.unit.registry_service_sync_helpers import (
    catalogue_naming,
    fetch_silver_repo,
    snapshot_silver_repos,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.registry import SyncResult
    from tests.unit.registry_service_sync_helpers import SilverSnapshot


@pytest.mark.asyncio
async def test_sync_dry_run_leaves_registry_unchanged(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    wildside_catalogue_path: Path,
) -> None:
    """A dry-run sync reports the counts it would produce without persisting."""
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="test-dry-run-1")

    result = await registry_service.sync_from_catalogue("test", dry_run=True)

    # The wildside catalogue declares exactly six repositories, so a preview
    # must report all six rather than a vague lower bound.
    assert result.repositories_created == 6, (
        "Dry run should report every repository it would create"
    )
    persisted = await snapshot_silver_repos(session_factory)
    assert persisted == [], "A dry run must persist no Silver rows"


_ALPHA_API_COMPONENT = """      - key: alpha-api
        name: Alpha API
        repository:
          owner: leynos
          name: alpha-api
          default_branch: {branch}"""

_ALPHA_RETIRED_COMPONENT = """      - key: alpha-retired
        name: Alpha Retired
        repository:
          owner: leynos
          name: alpha-retired
          default_branch: main"""


def _write_alpha_catalogue(path: Path, *, branch: str, retired: bool) -> None:
    """Write a one-project catalogue whose alpha-api branch is configurable."""
    components = [_ALPHA_API_COMPONENT.format(branch=branch)]
    if retired:
        components.append(_ALPHA_RETIRED_COMPONENT)
    path.write_text(
        "version: 1\nprojects:\n  - key: alpha\n    name: Alpha\n"
        "    components:\n" + "\n".join(components) + "\n",
        encoding="utf-8",
    )


async def _assert_dry_run_left_rows_unchanged(
    session_factory: async_sessionmaker[AsyncSession],
    result: SyncResult,
    before: Repository,
    snapshot_before: SilverSnapshot,
) -> None:
    """Assert the dry run reported changes but persisted none of them."""
    assert result.repositories_updated == 1, "Dry run should report one update"
    assert result.repositories_deactivated == 1, "Dry run should report one removal"
    assert await snapshot_silver_repos(session_factory) == snapshot_before, (
        "A dry run must leave every Silver row unchanged"
    )
    after = await fetch_silver_repo(session_factory, "leynos", "alpha-api")
    assert after is not None, "alpha-api should still exist after the dry run"
    assert after.default_branch == "main", "Dry run must not apply the branch change"
    assert after.last_synced_at == before.last_synced_at, (
        "Dry run must not advance the last-synced timestamp"
    )
    retired = await fetch_silver_repo(session_factory, "leynos", "alpha-retired")
    assert retired is not None, "alpha-retired should still exist after the dry run"
    assert retired.ingestion_enabled is True, (
        "Dry run must not disable a repository it would remove"
    )


@pytest.mark.asyncio
async def test_sync_dry_run_leaves_existing_rows_unchanged(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    tmp_path: Path,
) -> None:
    """A dry run reports updates and removals without persisting either."""
    initial = tmp_path / "catalogue-v1.yaml"
    _write_alpha_catalogue(initial, branch="main", retired=True)
    updated = tmp_path / "catalogue-v2.yaml"
    _write_alpha_catalogue(updated, branch="develop", retired=False)

    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(initial, commit_sha="dry-run-existing-1")
    await registry_service.sync_from_catalogue("test")
    before = await fetch_silver_repo(session_factory, "leynos", "alpha-api")
    assert before is not None, "The first sync should create alpha-api"
    snapshot_before = await snapshot_silver_repos(session_factory)

    await importer.import_path(updated, commit_sha="dry-run-existing-2")
    result = await registry_service.sync_from_catalogue("test", dry_run=True)

    await _assert_dry_run_left_rows_unchanged(
        session_factory, result, before, snapshot_before
    )


@dataclasses.dataclass
class _FlushState:
    """Flush bookkeeping shared by every session a test factory yields."""

    count: int = 0
    fail_on: int | None = None


class _FlushControllingSession:
    """Session proxy that counts flushes and can fail on a chosen one.

    The sync flushes once per slug while it walks the catalogue and once more
    at the end of a dry run. Failing on the first flush would abort before the
    per-slug pass finished, so a test that wants the dry run's own flush uses a
    count taken from an identical baseline run.
    """

    def __init__(self, session: AsyncSession, state: _FlushState) -> None:
        """Wrap the session and share its flush state with the factory."""
        self._session = session
        self._state = state

    def __getattr__(self, name: str) -> object:
        """Delegate every other attribute to the wrapped session."""
        return getattr(self._session, name)

    async def flush(self) -> None:
        """Count the flush, then delegate or fail as the state requests."""
        self._state.count += 1
        if self._state.fail_on is not None and self._state.count >= self._state.fail_on:
            msg = "UNIQUE constraint failed: repositories.github_owner"
            raise IntegrityError(msg, {}, Exception(msg))
        await self._session.flush()


def _flush_controlling_factory(
    session_factory: async_sessionmaker[AsyncSession],
    state: _FlushState,
) -> async_sessionmaker[AsyncSession]:
    """Build a session factory whose flushes are counted and conditionally fail."""

    @contextlib.asynccontextmanager
    async def factory() -> cabc.AsyncIterator[_FlushControllingSession]:
        """Yield a proxy that records every flush the sync performs."""
        async with session_factory() as session:
            yield _FlushControllingSession(session, state)

    return typ.cast("async_sessionmaker[AsyncSession]", factory)


@pytest.mark.asyncio
async def test_sync_dry_run_reports_a_flush_time_constraint_failure(
    session_factory: async_sessionmaker[AsyncSession],
    wildside_catalogue_path: Path,
) -> None:
    """A constraint failure in the dry run's final flush surfaces as an error."""
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="dry-run-flush-1")

    # A real run commits its per-slug flushes, so its count is where the dry
    # run's own flush must follow. Failing one flush later proves the dry run
    # reached that flush instead of aborting during the per-slug pass.
    baseline = _FlushState()
    baseline_service = RepositoryRegistryService(
        session_factory, _flush_controlling_factory(session_factory, baseline)
    )
    await baseline_service.sync_from_catalogue("test")
    assert baseline.count > 1, "The sync should flush once per slug"
    persisted_before = await snapshot_silver_repos(session_factory)

    failing = _FlushState(fail_on=baseline.count + 1)
    service = RepositoryRegistryService(
        session_factory, _flush_controlling_factory(session_factory, failing)
    )

    with pytest.raises(RegistrySyncError, match="Database error during sync"):
        await service.sync_from_catalogue("test", dry_run=True)

    assert failing.count == baseline.count + 1, (
        "The failure must happen on the dry run's final flush, not an earlier one"
    )
    persisted = await snapshot_silver_repos(session_factory)
    assert persisted == persisted_before, "A failed dry run must change no rows"


@pytest.mark.asyncio
async def test_sync_bounds_the_left_disabled_preview(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    tmp_path: Path,
) -> None:
    """More disabled repositories than the preview limit keep an exact count."""
    # Pin the documented limit instead of deriving it from the constant under
    # test, so widening the constant cannot silently widen the expectation too.
    assert LEFT_DISABLED_PREVIEW_LIMIT == 100, (
        "The disabled preview limit is a documented contract of 100 entries"
    )
    # 101 disabled linked rows exceed the preview, and the four enabled rows
    # must never appear in it. Without them the test could not distinguish a
    # preview of disabled rows from a preview of every linked row.
    disabled_total = 101
    repositories = [(f"repo-{index}", False) for index in range(disabled_total)]
    repositories += [(f"enabled-{index}", True) for index in range(4)]
    catalogue = tmp_path / "catalogue.yaml"
    catalogue.write_text(
        catalogue_naming(tuple(name for name, _is_enabled in repositories)),
        encoding="utf-8",
    )

    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(catalogue, commit_sha="preview-boundary-1")

    async with session_factory() as session, session.begin():
        estate_id = await session.scalar(select(Estate.id).where(Estate.key == "test"))
        assert estate_id is not None, "The imported estate should exist"
        records = (await session.scalars(select(RepositoryRecord))).all()
        expected_ingestion = dict(repositories)
        for record in records:
            session.add(
                Repository(
                    github_owner=record.owner,
                    github_name=record.name,
                    default_branch=record.default_branch,
                    estate_id=estate_id,
                    catalogue_repository_id=record.id,
                    ingestion_enabled=expected_ingestion[record.name],
                    documentation_paths=[],
                )
            )

    result = await registry_service.sync_from_catalogue("test")

    assert result.repositories_left_disabled_count == disabled_total, (
        "The count must cover every disabled repository, not just the preview"
    )
    assert len(result.repositories_left_disabled) == 100, (
        "The preview list must stop at exactly 100 entries"
    )
    assert len(set(result.repositories_left_disabled)) == 100, (
        "The preview list must not contain duplicate slugs"
    )
    disabled_slugs = {
        f"leynos/{name}" for name, is_enabled in repositories if not is_enabled
    }
    assert set(result.repositories_left_disabled) <= disabled_slugs, (
        "The preview must never include a repository that is still enabled"
    )
