"""Unit tests for RepositoryRegistryService catalogue syncing."""

from __future__ import annotations

import typing as typ

import pytest
from sqlalchemy import delete, select

from ghillie.catalogue import CatalogueImporter, RepositoryRecord
from ghillie.registry import RegistrySyncError
from ghillie.silver.storage import Repository
from tests.unit.conftest import RepositoryCreateSpec

if typ.TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.registry import RepositoryRegistryService
    from tests.unit.conftest import CreateRepoFn, FetchRepoFn


@pytest.mark.asyncio
async def test_sync_creates_silver_repository_from_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    wildside_catalogue_path: Path,
) -> None:
    """Catalogue repositories appear in Silver after sync."""
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="test-sync-1")

    result = await registry_service.sync_from_catalogue("test")

    assert result.repositories_created >= 1
    assert result.estate_key == "test"

    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == "leynos",
                Repository.github_name == "wildside",
            )
        )
        assert repo is not None
        assert repo.ingestion_enabled is True
        assert repo.catalogue_repository_id is not None
        assert repo.last_synced_at is not None


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
    assert result.repositories_updated >= 1

    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == "leynos",
                Repository.github_name == "wildside",
            )
        )
        assert repo is not None
        assert repo.default_branch == "main"
        assert repo.ingestion_enabled is True


@pytest.mark.asyncio
async def test_sync_disables_ingestion_for_inactive_catalogue_repository(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    wildside_catalogue_path: Path,
) -> None:
    """When a catalogue repository is inactive, Silver ingestion is disabled."""
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(
        wildside_catalogue_path, commit_sha="test-sync-inactive-1"
    )

    await registry_service.sync_from_catalogue("test")

    async with session_factory() as session, session.begin():
        cat_repo = await session.scalar(
            select(RepositoryRecord).where(
                RepositoryRecord.owner == "leynos",
                RepositoryRecord.name == "wildside",
            )
        )
        assert cat_repo is not None
        cat_repo.is_active = False

    await registry_service.sync_from_catalogue("test")

    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == "leynos",
                Repository.github_name == "wildside",
            )
        )
        assert repo is not None
        assert repo.ingestion_enabled is False


@pytest.mark.asyncio
async def test_sync_deactivates_removed_catalogue_repository(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    wildside_catalogue_path: Path,
) -> None:
    """Repositories removed from catalogue get ingestion disabled."""
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="test-sync-3")

    await registry_service.sync_from_catalogue("test")

    async with session_factory() as session, session.begin():
        await session.execute(
            delete(RepositoryRecord).where(
                RepositoryRecord.owner == "leynos",
                RepositoryRecord.name == "wildside-engine",
            )
        )

    result = await registry_service.sync_from_catalogue("test")
    assert result.repositories_deactivated >= 1

    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == "leynos",
                Repository.github_name == "wildside-engine",
            )
        )
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
    assert result.repositories_deactivated == 0

    repo = await fetch_repo("other-org", "other-repo")
    assert repo is not None
    assert repo.ingestion_enabled is True, "Estate B repo should remain enabled"
    assert repo.estate_id == estate_b_id


@pytest.mark.asyncio
async def test_sync_raises_for_nonexistent_estate(
    registry_service: RepositoryRegistryService,
) -> None:
    """sync_from_catalogue() raises RegistrySyncError for missing estate."""
    with pytest.raises(RegistrySyncError) as exc_info:
        await registry_service.sync_from_catalogue("nonexistent-estate")

    assert "nonexistent-estate" in str(exc_info.value)
    assert "Estate not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sync_copies_documentation_paths_from_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    wildside_catalogue_path: Path,
) -> None:
    """Documentation paths are copied from catalogue to Silver."""
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="test-docs")

    await registry_service.sync_from_catalogue("test")

    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == "leynos",
                Repository.github_name == "wildside",
            )
        )
        assert repo is not None
        assert "docs/roadmap.md" in repo.documentation_paths
        assert "docs/adr/" in repo.documentation_paths
