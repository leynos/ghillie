"""Unit tests for RepositoryRegistryService."""

from __future__ import annotations

import dataclasses
import typing as typ
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from ghillie.catalogue import (
    CatalogueImporter,
    RepositoryRecord,
)
from ghillie.catalogue.storage import Estate
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


@dataclasses.dataclass(frozen=True)
class IngestionToggleParams:
    """Parameters for ingestion toggle test cases."""

    initial_state: bool
    method_name: str
    expected_state: bool
    expect_change: bool


@dataclasses.dataclass(frozen=True)
class EstateFilteringParams:
    """Parameters for estate filtering test cases."""

    method_name: str
    create_disabled_repo: bool


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
        **kwargs: typ.Any,  # noqa: ANN401 - Repository accepts arbitrary extra fields
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


@pytest_asyncio.fixture
async def create_estates(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[str, str]:
    """Create two test estates and return their IDs."""
    async with session_factory() as session, session.begin():
        estate_a = Estate(key="estate-a", name="Estate A")
        estate_b = Estate(key="estate-b", name="Estate B")
        session.add_all([estate_a, estate_b])
        await session.flush()
        return estate_a.id, estate_b.id


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
async def test_sync_disables_ingestion_for_inactive_catalogue_repository(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """When a catalogue repository is inactive, Silver ingestion is disabled."""
    # Setup - import catalogue and run initial sync
    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    catalogue_path = Path("examples/wildside-catalogue.yaml")
    await importer.import_path(catalogue_path, commit_sha="test-sync-inactive-1")

    service = RepositoryRegistryService(session_factory, session_factory)
    await service.sync_from_catalogue("test")

    # Setup - mark catalogue repo inactive
    async with session_factory() as session, session.begin():
        cat_repo = await session.scalar(
            select(RepositoryRecord).where(
                RepositoryRecord.owner == "leynos",
                RepositoryRecord.name == "wildside",
            )
        )
        assert cat_repo is not None
        cat_repo.is_active = False

    # Execute - sync again, should disable ingestion in Silver
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
        assert repo.ingestion_enabled is False


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
    async with session_factory() as session, session.begin():
        await session.execute(
            delete(RepositoryRecord).where(
                RepositoryRecord.owner == "leynos",
                RepositoryRecord.name == "wildside-engine",
            )
        )

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
async def test_sync_does_not_deactivate_other_estate_repositories(
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    create_estates: tuple[str, str],
    fetch_repo: FetchRepoFn,
) -> None:
    """Syncing estate A should not deactivate repositories from estate B."""
    _estate_a_id, estate_b_id = create_estates

    # Setup - create a repository belonging to estate B
    await create_repo(
        session_factory,
        "other-org",
        "other-repo",
        ingestion_enabled=True,
        estate_id=estate_b_id,
        catalogue_repository_id="cat-repo-b",
    )

    # Execute - sync estate A (which has no catalogue repos)
    service = RepositoryRegistryService(session_factory, session_factory)
    result = await service.sync_from_catalogue("estate-a")

    # Verify - estate B's repository should NOT be deactivated
    assert result.repositories_deactivated == 0

    repo = await fetch_repo(session_factory, "other-org", "other-repo")
    assert repo is not None
    assert repo.ingestion_enabled is True, "Estate B repo should remain enabled"
    assert repo.estate_id == estate_b_id


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
async def test_disable_ingestion_returns_false_when_already_disabled(
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """disable_ingestion() returns False when already disabled."""
    # Setup
    await create_repo(session_factory, "test-org", "test-repo", ingestion_enabled=False)

    # Execute
    changed = await registry_service.disable_ingestion("test-org", "test-repo")

    # Verify
    assert changed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        pytest.param(
            IngestionToggleParams(
                initial_state=False,
                method_name="enable_ingestion",
                expected_state=True,
                expect_change=True,
            ),
            id="enable",
        ),
        pytest.param(
            IngestionToggleParams(
                initial_state=True,
                method_name="disable_ingestion",
                expected_state=False,
                expect_change=True,
            ),
            id="disable",
        ),
    ],
)
async def test_ingestion_toggle_updates_flag(
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
    params: IngestionToggleParams,
) -> None:
    """Test enable/disable ingestion methods update the flag correctly."""
    # Setup
    await create_repo(
        session_factory, "test-org", "test-repo", ingestion_enabled=params.initial_state
    )

    # Execute
    method = getattr(registry_service, params.method_name)
    changed = await method("test-org", "test-repo")

    # Verify
    assert changed is params.expect_change
    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == "test-org",
                Repository.github_name == "test-repo",
            )
        )
    assert repo is not None
    assert repo.ingestion_enabled is params.expected_state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "should_include_disabled"),
    [
        pytest.param("list_active_repositories", False, id="active_only"),
        pytest.param("list_all_repositories", True, id="all"),
    ],
)
async def test_list_repositories_filtering(  # noqa: PLR0913
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
    method_name: str,
    should_include_disabled: bool,  # noqa: FBT001
) -> None:
    """Test list methods correctly filter by ingestion status."""
    # Setup
    await create_repo(session_factory, "org", "enabled-repo", ingestion_enabled=True)
    await create_repo(session_factory, "org", "disabled-repo", ingestion_enabled=False)

    # Execute
    method = getattr(registry_service, method_name)
    repos = await method()

    # Verify
    slugs = {repo.slug for repo in repos}
    assert "org/enabled-repo" in slugs

    if should_include_disabled:
        assert "org/disabled-repo" in slugs
    else:
        assert "org/disabled-repo" not in slugs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        pytest.param(
            EstateFilteringParams(
                method_name="list_active_repositories",
                create_disabled_repo=False,
            ),
            id="active_only",
        ),
        pytest.param(
            EstateFilteringParams(
                method_name="list_all_repositories",
                create_disabled_repo=True,
            ),
            id="all",
        ),
    ],
)
async def test_list_repositories_filters_by_estate_id(  # noqa: PLR0913
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    create_estates: tuple[str, str],
    registry_service: RepositoryRegistryService,
    params: EstateFilteringParams,
) -> None:
    """Test list methods filter by estate_id correctly."""
    estate_a_id, estate_b_id = create_estates

    # Create repositories in both estates
    await create_repo(session_factory, "org", "estate-a-repo-1", estate_id=estate_a_id)
    if params.create_disabled_repo:
        await create_repo(
            session_factory,
            "org",
            "estate-a-repo-2",
            estate_id=estate_a_id,
            ingestion_enabled=False,
        )
    else:
        await create_repo(
            session_factory, "org", "estate-a-repo-2", estate_id=estate_a_id
        )
    await create_repo(session_factory, "org", "estate-b-repo-1", estate_id=estate_b_id)

    # Execute
    method = getattr(registry_service, params.method_name)
    repos = await method(estate_id=estate_a_id)

    # Verify - only repos from estate A are returned
    slugs = {repo.slug for repo in repos}
    assert "org/estate-a-repo-1" in slugs
    assert "org/estate-a-repo-2" in slugs
    assert "org/estate-b-repo-1" not in slugs
    assert all(repo.estate_id == estate_a_id for repo in repos)


@pytest.mark.asyncio
async def test_list_all_repositories_supports_pagination(
    session_factory: async_sessionmaker[AsyncSession],
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """Pagination returns stable pages in owner/name order."""
    await create_repo(session_factory, "b-org", "repo-1")
    await create_repo(session_factory, "a-org", "repo-2")
    await create_repo(session_factory, "a-org", "repo-1")
    await create_repo(session_factory, "c-org", "repo-0")

    first_page = await registry_service.list_all_repositories(limit=2)
    assert [repo.slug for repo in first_page] == [
        "a-org/repo-1",
        "a-org/repo-2",
    ]

    second_page = await registry_service.list_all_repositories(limit=2, offset=2)
    assert [repo.slug for repo in second_page] == [
        "b-org/repo-1",
        "c-org/repo-0",
    ]


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


@pytest.mark.asyncio
async def test_get_repository_by_slug_returns_none_for_invalid_format(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """get_repository_by_slug() returns None for slug without '/'."""
    # Execute
    service = RepositoryRegistryService(session_factory, session_factory)
    repo = await service.get_repository_by_slug("invalid-slug")

    # Verify
    assert repo is None


@pytest.mark.asyncio
async def test_disable_ingestion_raises_for_missing_repo(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """disable_ingestion() raises RepositoryNotFoundError for missing repo."""
    # Execute & Verify
    service = RepositoryRegistryService(session_factory, session_factory)
    with pytest.raises(RepositoryNotFoundError) as exc_info:
        await service.disable_ingestion("nonexistent", "repo")

    assert "nonexistent/repo" in str(exc_info.value)
