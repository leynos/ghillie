"""Unit tests for RepositoryRegistryService catalogue syncing."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from ghillie.catalogue import CatalogueImporter, RepositoryRecord
from ghillie.registry import RegistrySyncError, RepositoryRegistryService
from ghillie.silver.storage import Repository
from tests.fixtures.specs import RepositoryCreateSpec
from tests.unit.registry_service_sync_helpers import (
    fetch_silver_repo,
    snapshot_silver_repo,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.registry import SyncResult
    from tests.fixtures.specs import CreateRepoFn, FetchRepoFn


@pytest_asyncio.fixture
async def import_and_sync(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
) -> typ.Callable[[Path, str], typ.Awaitable[SyncResult]]:
    """Return a factory for importing catalogue and running sync."""

    async def _import_and_sync(
        catalogue_path: Path,
        commit_sha: str,
        estate_key: str = "test",
        estate_name: str = "Test Estate",
    ) -> SyncResult:
        """Import the catalogue at a path and return its sync result."""
        importer = CatalogueImporter(
            session_factory, estate_key=estate_key, estate_name=estate_name
        )
        await importer.import_path(catalogue_path, commit_sha=commit_sha)
        return await registry_service.sync_from_catalogue(estate_key)

    return _import_and_sync


@pytest.mark.asyncio
async def test_sync_creates_silver_repository_from_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    import_and_sync: typ.Callable[[Path, str], typ.Awaitable[SyncResult]],
    wildside_catalogue_path: Path,
) -> None:
    """Catalogue repositories appear in Silver after sync."""
    result = await import_and_sync(wildside_catalogue_path, "test-sync-1")

    assert result.repositories_created >= 1, "The sync should report a creation"
    assert result.estate_key == "test", "The result should name the synced estate"

    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None, "The catalogue repository should appear in Silver"
    assert repo.ingestion_enabled is True, "A new repository should ingest by default"
    assert repo.catalogue_repository_id is not None, (
        "The Silver row should link to its catalogue record"
    )
    assert repo.last_synced_at is not None, "The sync should stamp the sync time"


@pytest.mark.asyncio
async def test_sync_updates_existing_silver_repository(
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
    wildside_catalogue_path: Path,
) -> None:
    """Changes in catalogue propagate to Silver on sync."""
    await create_repo(
        "leynos",
        "wildside",
        spec=RepositoryCreateSpec(default_branch="develop", ingestion_enabled=False),
    )

    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="test-sync-2")

    result = await registry_service.sync_from_catalogue("test")
    assert result.repositories_updated >= 1, "The sync should report an update"

    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == "leynos",
                Repository.github_name == "wildside",
            )
        )
        assert repo is not None, "The existing Silver row should still exist"
        assert repo.default_branch == "main", (
            "The catalogue branch should overwrite the operator value"
        )
        assert repo.ingestion_enabled is True, (
            "A catalogue repository should be re-enabled by sync"
        )


@pytest.mark.asyncio
async def test_sync_disables_ingestion_for_inactive_catalogue_repository(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    import_and_sync: typ.Callable[[Path, str], typ.Awaitable[SyncResult]],
    wildside_catalogue_path: Path,
) -> None:
    """When a catalogue repository is inactive, Silver ingestion is disabled."""
    await import_and_sync(wildside_catalogue_path, "test-sync-inactive-1")

    async with session_factory() as session, session.begin():
        cat_repo = await session.scalar(
            select(RepositoryRecord).where(
                RepositoryRecord.owner == "leynos",
                RepositoryRecord.name == "wildside",
            )
        )
        assert cat_repo is not None, "The imported catalogue record should exist"
        cat_repo.is_active = False

    await registry_service.sync_from_catalogue("test")

    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None, "The Silver row should still exist"
    assert repo.ingestion_enabled is False, (
        "An inactive catalogue repository should have ingestion disabled"
    )


@pytest.mark.asyncio
async def test_sync_deactivates_removed_catalogue_repository(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    import_and_sync: typ.Callable[[Path, str], typ.Awaitable[SyncResult]],
    wildside_catalogue_path: Path,
) -> None:
    """Repositories removed from catalogue get ingestion disabled."""
    await import_and_sync(wildside_catalogue_path, "test-sync-3")

    async with session_factory() as session, session.begin():
        await session.execute(
            delete(RepositoryRecord).where(
                RepositoryRecord.owner == "leynos",
                RepositoryRecord.name == "wildside-engine",
            )
        )

    result = await registry_service.sync_from_catalogue("test")
    assert result.repositories_deactivated >= 1, (
        "The removed catalogue repository should be reported as deactivated"
    )

    repo = await fetch_silver_repo(session_factory, "leynos", "wildside-engine")
    assert repo is not None, "Repository should still exist in Silver"
    assert repo.ingestion_enabled is False, "Ingestion should be disabled"


@pytest.mark.asyncio
async def test_sync_does_not_deactivate_other_estate_repositories(
    create_estates: tuple[str, str],
    create_repo: CreateRepoFn,
    fetch_repo: FetchRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """Syncing estate A should not deactivate repositories from estate B."""
    _estate_a_id, estate_b_id = create_estates

    await create_repo(
        "other-org",
        "other-repo",
        spec=RepositoryCreateSpec(
            ingestion_enabled=True,
            estate_id=estate_b_id,
            catalogue_repository_id="cat-repo-b",
        ),
    )

    result = await registry_service.sync_from_catalogue("estate-a")
    assert result.repositories_deactivated == 0, (
        "Syncing one estate must not deactivate another estate's repositories"
    )

    repo = await fetch_repo("other-org", "other-repo")
    assert repo is not None, "Estate B's repository should still exist"
    assert repo.ingestion_enabled is True, "Estate B repo should remain enabled"
    assert repo.estate_id == estate_b_id, "Estate B's row must stay with estate B"


@pytest.mark.asyncio
async def test_sync_raises_for_nonexistent_estate(
    registry_service: RepositoryRegistryService,
) -> None:
    """sync_from_catalogue() raises RegistrySyncError for missing estate."""
    with pytest.raises(
        RegistrySyncError,
        match=r"^Sync failed for estate nonexistent-estate: Estate not found$",
    ):
        await registry_service.sync_from_catalogue("nonexistent-estate")


@pytest.mark.asyncio
async def test_sync_copies_documentation_paths_from_catalogue(
    registry_service: RepositoryRegistryService,
    import_and_sync: typ.Callable[[Path, str], typ.Awaitable[SyncResult]],
    wildside_catalogue_path: Path,
) -> None:
    """Documentation paths are copied from catalogue to Silver."""
    await import_and_sync(wildside_catalogue_path, "test-docs")

    repo = await registry_service.get_repository_by_slug("leynos/wildside")
    assert repo is not None, "The synced repository should be readable by slug"
    assert "docs/roadmap.md" in repo.documentation_paths, (
        "A catalogue documentation path should reach Silver"
    )
    assert "docs/adr/" in repo.documentation_paths, (
        "A catalogue documentation directory should reach Silver"
    )


@pytest.mark.asyncio
async def test_sync_preserves_operator_disable(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    import_and_sync: typ.Callable[[Path, str], typ.Awaitable[SyncResult]],
    wildside_catalogue_path: Path,
) -> None:
    """A later import and sync must not re-enable an operator-disabled repo."""
    await import_and_sync(wildside_catalogue_path, "test-preserve-1")
    assert await registry_service.disable_ingestion("leynos", "wildside") is True, (
        "The operator disable should succeed"
    )

    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="test-preserve-2")

    result = await registry_service.sync_from_catalogue("test")

    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None, "The repository should still exist after the sync"
    assert repo.ingestion_enabled is False, "Operator disable must survive a sync"
    assert "leynos/wildside" in result.repositories_left_disabled, (
        "The preserved disable should be reported"
    )
    assert result.repositories_left_disabled_count == 1, (
        "Exactly one repository should be reported as left disabled"
    )


@pytest.mark.asyncio
async def test_sync_keeps_readded_repository_disabled(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    import_and_sync: typ.Callable[[Path, str], typ.Awaitable[SyncResult]],
    wildside_catalogue_path: Path,
) -> None:
    """A repository removed and re-added stays disabled until an operator acts."""
    await import_and_sync(wildside_catalogue_path, "test-readd-1")

    # Simulate removal: deleting the catalogue record makes the next sync treat
    # the linked Silver row as removed. Re-importing then recreates the record
    # with a fresh id, so the Silver row's link is stale but still non-null.
    async with session_factory() as session, session.begin():
        await session.execute(
            delete(RepositoryRecord).where(
                RepositoryRecord.owner == "leynos",
                RepositoryRecord.name == "wildside-engine",
            )
        )
    removed = await registry_service.sync_from_catalogue("test")
    assert removed.repositories_deactivated >= 1, (
        "The removal sync should report the deactivation"
    )

    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="test-readd-2")

    readded = await registry_service.sync_from_catalogue("test")

    repo = await fetch_silver_repo(session_factory, "leynos", "wildside-engine")
    assert repo is not None, "The re-added repository should still exist"
    assert repo.ingestion_enabled is False, (
        "A re-added repository must stay disabled until an operator acts"
    )
    assert "leynos/wildside-engine" in readded.repositories_left_disabled, (
        "The re-added repository should be reported as left disabled"
    )


@pytest.mark.asyncio
async def test_sync_reports_cross_estate_conflict(
    session_factory: async_sessionmaker[AsyncSession],
    create_estates: tuple[str, str],
    create_repo: CreateRepoFn,
    wildside_catalogue_path: Path,
) -> None:
    """A repository owned by another estate is reported, not stolen or failed."""
    registry_service = RepositoryRegistryService(session_factory, session_factory)
    _estate_a_id, estate_b_id = create_estates
    foreign_synced_at = dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.UTC)
    await create_repo(
        "leynos",
        "wildside",
        spec=RepositoryCreateSpec(
            ingestion_enabled=True,
            default_branch="release",
            estate_id=estate_b_id,
            catalogue_repository_id="cat-repo-b",
            documentation_paths=("docs/other-estate.md",),
            last_synced_at=foreign_synced_at,
        ),
    )
    before = await snapshot_silver_repo(session_factory, "leynos", "wildside")

    importer = CatalogueImporter(
        session_factory, estate_key="estate-a", estate_name="Estate A"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="test-conflict-1")

    result = await registry_service.sync_from_catalogue("estate-a")

    assert "leynos/wildside" in result.repositories_conflicted, (
        "A repository owned by another estate should be reported as a conflict"
    )
    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None, "The conflicting repository should still exist"
    assert repo.estate_id == estate_b_id, "The row must stay with its owning estate"
    assert repo.ingestion_enabled is True, "A conflict must not disable the row"
    assert repo.catalogue_repository_id == "cat-repo-b", (
        "A conflict must not re-point the row at this estate's catalogue entry"
    )
    assert repo.default_branch == "release", (
        "A conflict must not overwrite the owning estate's branch metadata"
    )
    assert tuple(repo.documentation_paths) == ("docs/other-estate.md",), (
        "A conflict must not overwrite the owning estate's documentation paths"
    )
    assert repo.last_synced_at == foreign_synced_at, (
        "A conflict must not restamp the owning estate's last sync time"
    )
    assert (
        await snapshot_silver_repo(session_factory, "leynos", "wildside") == before
    ), "A conflict must leave every field of the foreign row untouched"
