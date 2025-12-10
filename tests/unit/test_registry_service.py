"""Unit tests for RepositoryRegistryService."""

from __future__ import annotations

import typing as typ
from pathlib import Path

import pytest
from sqlalchemy import select

from ghillie.catalogue import (
    CatalogueImporter,
    RepositoryRecord,
)
from ghillie.registry import (
    RegistrySyncError,
    RepositoryNotFoundError,
    RepositoryRegistryService,
)
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    # Type aliases for fixture return types
    CreateRepoFn = cabc.Callable[..., cabc.Coroutine[typ.Any, typ.Any, None]]
    FetchRepoFn = cabc.Callable[
        [async_sessionmaker[AsyncSession], str, str],
        cabc.Coroutine[typ.Any, typ.Any, Repository | None],
    ]


@pytest.fixture
def create_repo() -> CreateRepoFn:
    """Return a factory for creating test repositories."""

    async def _create(  # noqa: PLR0913
        session_factory: async_sessionmaker[AsyncSession],
        owner: str,
        name: str,
        *,
        ingestion_enabled: bool = True,
        default_branch: str = "main",
        **kwargs: typ.Any,  # noqa: ANN401
    ) -> None:
        async with session_factory() as session, session.begin():
            repo = Repository(
                github_owner=owner,
                github_name=name,
                default_branch=default_branch,
                ingestion_enabled=ingestion_enabled,
                **kwargs,
            )
            session.add(repo)

    return _create


@pytest.fixture
def fetch_repo() -> FetchRepoFn:
    """Return a factory for fetching repositories by owner/name."""

    async def _fetch(
        session_factory: async_sessionmaker[AsyncSession],
        owner: str,
        name: str,
    ) -> Repository | None:
        async with session_factory() as session:
            return await session.scalar(
                select(Repository).where(
                    Repository.github_owner == owner,
                    Repository.github_name == name,
                )
            )

    return _fetch


@pytest.fixture
def registry_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> RepositoryRegistryService:
    """Return a RepositoryRegistryService instance for testing."""
    return RepositoryRegistryService(session_factory, session_factory)


@pytest.mark.asyncio
async def test_sync_creates_silver_repository_from_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Catalogue repositories appear in Silver after sync."""
    # Setup
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    catalogue_path = Path("examples/wildside-catalogue.yaml")
    await importer.import_path(catalogue_path, commit_sha="test-sync-1")

    # Execute
    service = RepositoryRegistryService(session_factory, session_factory)
    result = await service.sync_from_catalogue("test")

    # Verify
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
) -> None:
    """Changes in catalogue propagate to Silver on sync."""
    # Setup - create an existing Silver repository
    async with session_factory() as session, session.begin():
        repo = Repository(
            github_owner="leynos",
            github_name="wildside",
            default_branch="develop",  # Different from catalogue
            ingestion_enabled=False,  # Will be re-enabled
        )
        session.add(repo)

    # Setup - import catalogue
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    catalogue_path = Path("examples/wildside-catalogue.yaml")
    await importer.import_path(catalogue_path, commit_sha="test-sync-2")

    # Execute
    service = RepositoryRegistryService(session_factory, session_factory)
    result = await service.sync_from_catalogue("test")

    # Verify
    assert result.repositories_updated >= 1

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


@pytest.mark.asyncio
async def test_sync_deactivates_removed_catalogue_repository(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repositories removed from catalogue get ingestion disabled."""
    # Setup - import catalogue
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    catalogue_path = Path("examples/wildside-catalogue.yaml")
    await importer.import_path(catalogue_path, commit_sha="test-sync-3")

    # Setup - run initial sync
    service = RepositoryRegistryService(session_factory, session_factory)
    await service.sync_from_catalogue("test")

    # Setup - delete the repo from catalogue
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

    # Execute - run sync again - should deactivate the removed repo
    result = await service.sync_from_catalogue("test")

    # Verify
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
async def test_enable_ingestion_updates_flag(
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    fetch_repo: FetchRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """enable_ingestion() sets the flag to True."""
    # Setup
    await create_repo(session_factory, "test-org", "test-repo", ingestion_enabled=False)

    # Execute
    changed = await registry_service.enable_ingestion("test-org", "test-repo")

    # Verify
    assert changed is True
    repo = await fetch_repo(session_factory, "test-org", "test-repo")
    assert repo is not None
    assert repo.ingestion_enabled is True


@pytest.mark.asyncio
async def test_disable_ingestion_updates_flag(
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    fetch_repo: FetchRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """disable_ingestion() sets the flag to False."""
    # Setup
    await create_repo(session_factory, "test-org", "test-repo", ingestion_enabled=True)

    # Execute
    changed = await registry_service.disable_ingestion("test-org", "test-repo")

    # Verify
    assert changed is True
    repo = await fetch_repo(session_factory, "test-org", "test-repo")
    assert repo is not None
    assert repo.ingestion_enabled is False


@pytest.mark.asyncio
async def test_enable_ingestion_returns_false_when_already_enabled(
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """enable_ingestion() returns False when already enabled."""
    # Setup
    await create_repo(session_factory, "test-org", "test-repo", ingestion_enabled=True)

    # Execute
    changed = await registry_service.enable_ingestion("test-org", "test-repo")

    # Verify
    assert changed is False


@pytest.mark.asyncio
async def test_enable_ingestion_raises_for_missing_repo(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """enable_ingestion() raises RepositoryNotFoundError for missing repo."""
    # Execute & Verify
    service = RepositoryRegistryService(session_factory, session_factory)
    with pytest.raises(RepositoryNotFoundError) as exc_info:
        await service.enable_ingestion("nonexistent", "repo")

    assert "nonexistent/repo" in str(exc_info.value)


@pytest.mark.asyncio
async def test_list_active_repositories_respects_ingestion_flag(
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """Only repositories with ingestion_enabled=True are returned."""
    # Setup
    await create_repo(session_factory, "org", "enabled-repo", ingestion_enabled=True)
    await create_repo(session_factory, "org", "disabled-repo", ingestion_enabled=False)

    # Execute
    repos = await registry_service.list_active_repositories()

    # Verify
    slugs = {repo.slug for repo in repos}
    assert "org/enabled-repo" in slugs
    assert "org/disabled-repo" not in slugs


@pytest.mark.asyncio
async def test_list_all_repositories_includes_disabled(
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """list_all_repositories() includes disabled repositories."""
    # Setup
    await create_repo(session_factory, "org", "enabled-repo", ingestion_enabled=True)
    await create_repo(session_factory, "org", "disabled-repo", ingestion_enabled=False)

    # Execute
    repos = await registry_service.list_all_repositories()

    # Verify
    slugs = {repo.slug for repo in repos}
    assert "org/enabled-repo" in slugs
    assert "org/disabled-repo" in slugs


@pytest.mark.asyncio
async def test_get_repository_by_slug_returns_info(
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """get_repository_by_slug() returns RepositoryInfo for existing repo."""
    # Setup
    await create_repo(
        session_factory,
        "test-org",
        "test-repo",
        ingestion_enabled=True,
        documentation_paths=["docs/roadmap.md"],
    )

    # Execute
    repo = await registry_service.get_repository_by_slug("test-org/test-repo")

    # Verify
    assert repo is not None
    assert repo.owner == "test-org"
    assert repo.name == "test-repo"
    assert repo.slug == "test-org/test-repo"
    assert repo.ingestion_enabled is True
    assert "docs/roadmap.md" in repo.documentation_paths


@pytest.mark.asyncio
async def test_get_repository_by_slug_returns_none_for_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """get_repository_by_slug() returns None for missing repo."""
    # Execute
    service = RepositoryRegistryService(session_factory, session_factory)
    repo = await service.get_repository_by_slug("nonexistent/repo")

    # Verify
    assert repo is None


@pytest.mark.asyncio
async def test_sync_raises_for_nonexistent_estate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """sync_from_catalogue() raises RegistrySyncError for missing estate."""
    # Execute & Verify
    service = RepositoryRegistryService(session_factory, session_factory)
    with pytest.raises(RegistrySyncError) as exc_info:
        await service.sync_from_catalogue("nonexistent-estate")

    assert "nonexistent-estate" in str(exc_info.value)
    assert "Estate not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sync_copies_documentation_paths_from_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Documentation paths are copied from catalogue to Silver."""
    # Setup & Execute
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    catalogue_path = Path("examples/wildside-catalogue.yaml")
    await importer.import_path(catalogue_path, commit_sha="test-docs")

    service = RepositoryRegistryService(session_factory, session_factory)
    await service.sync_from_catalogue("test")

    # Verify
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
