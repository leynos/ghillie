"""Dry-run and preview tests for RepositoryRegistryService catalogue syncing."""

from __future__ import annotations

import contextlib
import functools
import typing as typ

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ghillie.catalogue import CatalogueImporter, Estate, RepositoryRecord
from ghillie.registry import RegistrySyncError, RepositoryRegistryService
from ghillie.registry.models import LEFT_DISABLED_PREVIEW_LIMIT
from ghillie.silver.storage import Repository
from tests.unit.registry_service_sync_helpers import (
    fetch_silver_repo,
    snapshot_silver_repos,
)

if typ.TYPE_CHECKING:
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

    assert result.repositories_created >= 1, "Dry run should report creations"
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


class _FlushFailingSession:
    """Session proxy whose flush reports a constraint violation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __getattr__(self, name: str) -> object:
        return getattr(self._session, name)

    async def flush(self) -> None:
        msg = "UNIQUE constraint failed: repositories.github_owner"
        raise IntegrityError(msg, {}, Exception(msg))


@contextlib.asynccontextmanager
async def _flush_failing_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> typ.AsyncIterator[_FlushFailingSession]:
    async with session_factory() as session:
        yield _FlushFailingSession(session)


@pytest.mark.asyncio
async def test_sync_dry_run_reports_a_flush_time_constraint_failure(
    session_factory: async_sessionmaker[AsyncSession],
    wildside_catalogue_path: Path,
) -> None:
    """A constraint failure during the dry-run flush surfaces as a sync error."""
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="dry-run-flush-1")
    silver_factory = typ.cast(
        "async_sessionmaker[AsyncSession]",
        functools.partial(_flush_failing_factory, session_factory),
    )
    service = RepositoryRegistryService(session_factory, silver_factory)

    with pytest.raises(RegistrySyncError, match="Database error during sync"):
        await service.sync_from_catalogue("test", dry_run=True)

    persisted = await snapshot_silver_repos(session_factory)
    assert persisted == [], "A failed dry run must persist no Silver rows"


@pytest.mark.asyncio
async def test_sync_bounds_the_left_disabled_preview(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    tmp_path: Path,
) -> None:
    """More disabled repositories than the preview limit keep an exact count."""
    total = LEFT_DISABLED_PREVIEW_LIMIT + 1
    lines = ["version: 1", "projects:"]
    for index in range(total):
        lines.extend(
            [
                f"  - key: project-{index}",
                f"    name: Project {index}",
                "    components:",
                f"      - key: component-{index}",
                f"        name: Component {index}",
                "        repository:",
                "          owner: leynos",
                f"          name: repo-{index}",
                "          default_branch: main",
            ]
        )
    catalogue = tmp_path / "catalogue.yaml"
    catalogue.write_text("\n".join(lines) + "\n", encoding="utf-8")

    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(catalogue, commit_sha="preview-boundary-1")

    async with session_factory() as session, session.begin():
        estate_id = await session.scalar(select(Estate.id).where(Estate.key == "test"))
        assert estate_id is not None, "The imported estate should exist"
        records = (await session.scalars(select(RepositoryRecord))).all()
        for record in records:
            session.add(
                Repository(
                    github_owner=record.owner,
                    github_name=record.name,
                    default_branch=record.default_branch,
                    estate_id=estate_id,
                    catalogue_repository_id=record.id,
                    ingestion_enabled=False,
                    documentation_paths=[],
                )
            )

    result = await registry_service.sync_from_catalogue("test")

    assert result.repositories_left_disabled_count == total, (
        "The count must cover every disabled repository, not just the preview"
    )
    assert len(result.repositories_left_disabled) == LEFT_DISABLED_PREVIEW_LIMIT, (
        "The preview list must stop at the configured limit"
    )
    assert len(set(result.repositories_left_disabled)) == LEFT_DISABLED_PREVIEW_LIMIT, (
        "The preview list must not contain duplicate slugs"
    )
