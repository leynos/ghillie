"""Unit tests for RepositoryRegistryService."""

from __future__ import annotations

import asyncio
import typing as typ

import pytest
from sqlalchemy import select

from ghillie.catalogue import (
    CatalogueImporter,
    RepositoryRecord,
)
from ghillie.registry import (
    RegistrySyncError,
    RepositoryInfo,
    RepositoryNotFoundError,
    RepositoryRegistryService,
    SyncResult,
)
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_sync_creates_silver_repository_from_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Catalogue repositories appear in Silver after sync."""

    async def _run() -> SyncResult:
        # Import catalogue first
        importer = CatalogueImporter(
            session_factory, estate_key="test", estate_name="Test Estate"
        )
        from pathlib import Path

        catalogue_path = Path("examples/wildside-catalogue.yaml")
        await importer.import_path(catalogue_path, commit_sha="test-sync-1")

        # Run registry sync
        service = RepositoryRegistryService(session_factory, session_factory)
        return await service.sync_from_catalogue("test")

    result = asyncio.run(_run())

    assert result.repositories_created >= 1
    assert result.estate_key == "test"

    async def _verify() -> None:
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

    asyncio.run(_verify())


def test_sync_updates_existing_silver_repository(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Changes in catalogue propagate to Silver on sync."""

    async def _setup() -> None:
        # Create an existing Silver repository
        async with session_factory() as session, session.begin():
            repo = Repository(
                github_owner="leynos",
                github_name="wildside",
                default_branch="develop",  # Different from catalogue
                ingestion_enabled=False,  # Will be re-enabled
            )
            session.add(repo)

        # Import catalogue
        importer = CatalogueImporter(
            session_factory, estate_key="test", estate_name="Test Estate"
        )
        from pathlib import Path

        catalogue_path = Path("examples/wildside-catalogue.yaml")
        await importer.import_path(catalogue_path, commit_sha="test-sync-2")

    asyncio.run(_setup())

    async def _sync() -> SyncResult:
        service = RepositoryRegistryService(session_factory, session_factory)
        return await service.sync_from_catalogue("test")

    result = asyncio.run(_sync())
    assert result.repositories_updated >= 1

    async def _verify() -> None:
        async with session_factory() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == "leynos",
                    Repository.github_name == "wildside",
                )
            )
            assert repo is not None
            assert repo.default_branch == "main"  # Updated from catalogue
            assert repo.ingestion_enabled is True  # Re-enabled

    asyncio.run(_verify())


def test_sync_deactivates_removed_catalogue_repository(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repositories removed from catalogue get ingestion disabled."""

    async def _setup_and_sync() -> SyncResult:
        # Import catalogue first
        importer = CatalogueImporter(
            session_factory, estate_key="test", estate_name="Test Estate"
        )
        from pathlib import Path

        catalogue_path = Path("examples/wildside-catalogue.yaml")
        await importer.import_path(catalogue_path, commit_sha="test-sync-3")

        # Run initial sync
        service = RepositoryRegistryService(session_factory, session_factory)
        await service.sync_from_catalogue("test")

        # Delete the repo from catalogue
        async with session_factory() as session:
            cat_repo = await session.scalar(
                select(RepositoryRecord).where(
                    RepositoryRecord.owner == "leynos",
                    RepositoryRecord.name == "wildside-engine",
                )
            )

            if cat_repo:
                await session.delete(cat_repo)
                await session.commit()

        # Run sync again - should deactivate the removed repo
        return await service.sync_from_catalogue("test")

    result = asyncio.run(_setup_and_sync())
    assert result.repositories_deactivated >= 1

    async def _verify() -> None:
        async with session_factory() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == "leynos",
                    Repository.github_name == "wildside-engine",
                )
            )
            assert repo is not None, "Repository should still exist in Silver"
            assert repo.ingestion_enabled is False, "Ingestion should be disabled"

    asyncio.run(_verify())


def test_enable_ingestion_updates_flag(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """enable_ingestion() sets the flag to True."""

    async def _setup() -> None:
        async with session_factory() as session, session.begin():
            repo = Repository(
                github_owner="test-org",
                github_name="test-repo",
                default_branch="main",
                ingestion_enabled=False,
            )
            session.add(repo)

    asyncio.run(_setup())

    async def _enable() -> bool:
        service = RepositoryRegistryService(session_factory, session_factory)
        return await service.enable_ingestion("test-org", "test-repo")

    changed = asyncio.run(_enable())
    assert changed is True

    async def _verify() -> None:
        async with session_factory() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == "test-org",
                    Repository.github_name == "test-repo",
                )
            )
            assert repo is not None
            assert repo.ingestion_enabled is True

    asyncio.run(_verify())


def test_disable_ingestion_updates_flag(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """disable_ingestion() sets the flag to False."""

    async def _setup() -> None:
        async with session_factory() as session, session.begin():
            repo = Repository(
                github_owner="test-org",
                github_name="test-repo",
                default_branch="main",
                ingestion_enabled=True,
            )
            session.add(repo)

    asyncio.run(_setup())

    async def _disable() -> bool:
        service = RepositoryRegistryService(session_factory, session_factory)
        return await service.disable_ingestion("test-org", "test-repo")

    changed = asyncio.run(_disable())
    assert changed is True

    async def _verify() -> None:
        async with session_factory() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == "test-org",
                    Repository.github_name == "test-repo",
                )
            )
            assert repo is not None
            assert repo.ingestion_enabled is False

    asyncio.run(_verify())


def test_enable_ingestion_returns_false_when_already_enabled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """enable_ingestion() returns False when already enabled."""

    async def _setup() -> None:
        async with session_factory() as session, session.begin():
            repo = Repository(
                github_owner="test-org",
                github_name="test-repo",
                default_branch="main",
                ingestion_enabled=True,
            )
            session.add(repo)

    asyncio.run(_setup())

    async def _enable() -> bool:
        service = RepositoryRegistryService(session_factory, session_factory)
        return await service.enable_ingestion("test-org", "test-repo")

    changed = asyncio.run(_enable())
    assert changed is False


def test_enable_ingestion_raises_for_missing_repo(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """enable_ingestion() raises RepositoryNotFoundError for missing repo."""

    async def _enable() -> None:
        service = RepositoryRegistryService(session_factory, session_factory)
        await service.enable_ingestion("nonexistent", "repo")

    with pytest.raises(RepositoryNotFoundError) as exc_info:
        asyncio.run(_enable())

    assert "nonexistent/repo" in str(exc_info.value)


def test_list_active_repositories_respects_ingestion_flag(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Only repositories with ingestion_enabled=True are returned."""

    async def _setup() -> None:
        async with session_factory() as session, session.begin():
            session.add(
                Repository(
                    github_owner="org",
                    github_name="enabled-repo",
                    default_branch="main",
                    ingestion_enabled=True,
                )
            )
            session.add(
                Repository(
                    github_owner="org",
                    github_name="disabled-repo",
                    default_branch="main",
                    ingestion_enabled=False,
                )
            )

    asyncio.run(_setup())

    async def _list() -> list[RepositoryInfo]:
        service = RepositoryRegistryService(session_factory, session_factory)
        return await service.list_active_repositories()

    repos = asyncio.run(_list())
    slugs = {repo.slug for repo in repos}

    assert "org/enabled-repo" in slugs
    assert "org/disabled-repo" not in slugs


def test_list_all_repositories_includes_disabled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """list_all_repositories() includes disabled repositories."""

    async def _setup() -> None:
        async with session_factory() as session, session.begin():
            session.add(
                Repository(
                    github_owner="org",
                    github_name="enabled-repo",
                    default_branch="main",
                    ingestion_enabled=True,
                )
            )
            session.add(
                Repository(
                    github_owner="org",
                    github_name="disabled-repo",
                    default_branch="main",
                    ingestion_enabled=False,
                )
            )

    asyncio.run(_setup())

    async def _list() -> list[RepositoryInfo]:
        service = RepositoryRegistryService(session_factory, session_factory)
        return await service.list_all_repositories()

    repos = asyncio.run(_list())
    slugs = {repo.slug for repo in repos}

    assert "org/enabled-repo" in slugs
    assert "org/disabled-repo" in slugs


def test_get_repository_by_slug_returns_info(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """get_repository_by_slug() returns RepositoryInfo for existing repo."""

    async def _setup() -> None:
        async with session_factory() as session, session.begin():
            session.add(
                Repository(
                    github_owner="test-org",
                    github_name="test-repo",
                    default_branch="main",
                    ingestion_enabled=True,
                    documentation_paths=["docs/roadmap.md"],
                )
            )

    asyncio.run(_setup())

    async def _get() -> RepositoryInfo | None:
        service = RepositoryRegistryService(session_factory, session_factory)
        return await service.get_repository_by_slug("test-org/test-repo")

    repo = asyncio.run(_get())

    assert repo is not None
    assert repo.owner == "test-org"
    assert repo.name == "test-repo"
    assert repo.slug == "test-org/test-repo"
    assert repo.ingestion_enabled is True
    assert "docs/roadmap.md" in repo.documentation_paths


def test_get_repository_by_slug_returns_none_for_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """get_repository_by_slug() returns None for missing repo."""

    async def _get() -> RepositoryInfo | None:
        service = RepositoryRegistryService(session_factory, session_factory)
        return await service.get_repository_by_slug("nonexistent/repo")

    repo = asyncio.run(_get())
    assert repo is None


def test_sync_raises_for_nonexistent_estate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """sync_from_catalogue() raises RegistrySyncError for missing estate."""

    async def _sync() -> None:
        service = RepositoryRegistryService(session_factory, session_factory)
        await service.sync_from_catalogue("nonexistent-estate")

    with pytest.raises(RegistrySyncError) as exc_info:
        asyncio.run(_sync())

    assert "nonexistent-estate" in str(exc_info.value)
    assert "Estate not found" in str(exc_info.value)


def test_sync_copies_documentation_paths_from_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Documentation paths are copied from catalogue to Silver."""

    async def _run() -> None:
        # Import catalogue
        importer = CatalogueImporter(
            session_factory, estate_key="test", estate_name="Test Estate"
        )
        from pathlib import Path

        catalogue_path = Path("examples/wildside-catalogue.yaml")
        await importer.import_path(catalogue_path, commit_sha="test-docs")

        # Run sync
        service = RepositoryRegistryService(session_factory, session_factory)
        await service.sync_from_catalogue("test")

    asyncio.run(_run())

    async def _verify() -> None:
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

    asyncio.run(_verify())
