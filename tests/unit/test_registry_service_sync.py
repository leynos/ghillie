"""Unit tests for RepositoryRegistryService catalogue syncing."""

from __future__ import annotations

import contextlib
import functools
import typing as typ

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from ghillie.catalogue import CatalogueImporter, Estate, RepositoryRecord
from ghillie.registry import RegistrySyncError, RepositoryRegistryService
from ghillie.registry.models import LEFT_DISABLED_PREVIEW_LIMIT
from ghillie.silver.storage import Repository
from tests.fixtures.specs import RepositoryCreateSpec

if typ.TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.registry import SyncResult
    from tests.fixtures.specs import CreateRepoFn, FetchRepoFn


async def fetch_silver_repo(
    session_factory: async_sessionmaker[AsyncSession],
    owner: str,
    name: str,
) -> Repository | None:
    """Fetch a repository from Silver by owner/name."""
    async with session_factory() as session:
        return await session.scalar(
            select(Repository).where(
                Repository.github_owner == owner,
                Repository.github_name == name,
            )
        )


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

    assert result.repositories_created >= 1
    assert result.estate_key == "test"

    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
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
        assert cat_repo is not None
        cat_repo.is_active = False

    await registry_service.sync_from_catalogue("test")

    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None
    assert repo.ingestion_enabled is False


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
    assert result.repositories_deactivated >= 1

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
    assert repo is not None
    assert "docs/roadmap.md" in repo.documentation_paths
    assert "docs/adr/" in repo.documentation_paths


@pytest.mark.asyncio
async def test_sync_preserves_operator_disable(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    import_and_sync: typ.Callable[[Path, str], typ.Awaitable[SyncResult]],
    wildside_catalogue_path: Path,
) -> None:
    """A later import and sync must not re-enable an operator-disabled repo."""
    await import_and_sync(wildside_catalogue_path, "test-preserve-1")
    assert await registry_service.disable_ingestion("leynos", "wildside") is True

    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="test-preserve-2")

    result = await registry_service.sync_from_catalogue("test")

    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None
    assert repo.ingestion_enabled is False
    assert "leynos/wildside" in result.repositories_left_disabled
    assert result.repositories_left_disabled_count == 1


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
    assert removed.repositories_deactivated >= 1

    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="test-readd-2")

    readded = await registry_service.sync_from_catalogue("test")

    repo = await fetch_silver_repo(session_factory, "leynos", "wildside-engine")
    assert repo is not None
    assert repo.ingestion_enabled is False
    assert "leynos/wildside-engine" in readded.repositories_left_disabled


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
    await create_repo(
        "leynos",
        "wildside",
        spec=RepositoryCreateSpec(
            ingestion_enabled=True,
            estate_id=estate_b_id,
            catalogue_repository_id="cat-repo-b",
        ),
    )

    importer = CatalogueImporter(
        session_factory, estate_key="estate-a", estate_name="Estate A"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="test-conflict-1")

    result = await registry_service.sync_from_catalogue("estate-a")

    assert "leynos/wildside" in result.repositories_conflicted
    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None
    assert repo.estate_id == estate_b_id
    assert repo.ingestion_enabled is True


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

    assert result.repositories_created >= 1
    assert await fetch_silver_repo(session_factory, "leynos", "wildside") is None


@pytest.mark.asyncio
async def test_sync_dry_run_leaves_existing_rows_unchanged(
    session_factory: async_sessionmaker[AsyncSession],
    registry_service: RepositoryRegistryService,
    tmp_path: Path,
) -> None:
    """A dry run reports updates and removals without persisting either."""
    initial = tmp_path / "catalogue-v1.yaml"
    initial.write_text(
        """
version: 1
projects:
  - key: alpha
    name: Alpha
    components:
      - key: alpha-api
        name: Alpha API
        repository:
          owner: leynos
          name: alpha-api
          default_branch: main
      - key: alpha-retired
        name: Alpha Retired
        repository:
          owner: leynos
          name: alpha-retired
          default_branch: main
""",
        encoding="utf-8",
    )
    updated = tmp_path / "catalogue-v2.yaml"
    updated.write_text(
        """
version: 1
projects:
  - key: alpha
    name: Alpha
    components:
      - key: alpha-api
        name: Alpha API
        repository:
          owner: leynos
          name: alpha-api
          default_branch: develop
""",
        encoding="utf-8",
    )

    importer = CatalogueImporter(
        session_factory, estate_key="test", estate_name="Test Estate"
    )
    await importer.import_path(initial, commit_sha="dry-run-existing-1")
    await registry_service.sync_from_catalogue("test")
    before = await fetch_silver_repo(session_factory, "leynos", "alpha-api")
    assert before is not None

    await importer.import_path(updated, commit_sha="dry-run-existing-2")
    result = await registry_service.sync_from_catalogue("test", dry_run=True)

    assert result.repositories_updated == 1
    assert result.repositories_deactivated == 1
    after = await fetch_silver_repo(session_factory, "leynos", "alpha-api")
    assert after is not None
    assert after.default_branch == "main"
    assert after.last_synced_at == before.last_synced_at
    retired = await fetch_silver_repo(session_factory, "leynos", "alpha-retired")
    assert retired is not None
    assert retired.ingestion_enabled is True


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
        assert estate_id is not None
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

    assert result.repositories_left_disabled_count == total
    assert len(result.repositories_left_disabled) == LEFT_DISABLED_PREVIEW_LIMIT
    assert len(set(result.repositories_left_disabled)) == LEFT_DISABLED_PREVIEW_LIMIT
