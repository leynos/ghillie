"""Behavioural tests for repository discovery and registration."""

from __future__ import annotations

import asyncio
import typing as typ
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenario, then, when
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ghillie.bronze import init_bronze_storage
from ghillie.catalogue import (
    CatalogueImporter,
    RepositoryRecord,
    init_catalogue_storage,
)
from ghillie.registry import RepositoryInfo, RepositoryRegistryService, SyncResult
from ghillie.silver import init_silver_storage
from ghillie.silver.storage import Repository


class DiscoveryContext(typ.TypedDict, total=False):
    """Shared state used by BDD steps."""

    session_factory: async_sessionmaker[AsyncSession]
    importer: CatalogueImporter
    service: RepositoryRegistryService
    sync_result: SyncResult
    active_repos: list[RepositoryInfo]


@scenario(
    "../repository_discovery.feature",
    "Catalogue repositories are registered for ingestion",
)
def test_catalogue_repos_registered() -> None:
    """Behavioural test: catalogue repos appear in Silver after sync."""


@scenario(
    "../repository_discovery.feature",
    "Removing a repository from catalogue disables ingestion",
)
def test_removed_repo_disabled() -> None:
    """Behavioural test: removed catalogue repo has ingestion disabled."""


@scenario(
    "../repository_discovery.feature",
    "Ingestion can be toggled per repository",
)
def test_ingestion_toggle() -> None:
    """Behavioural test: ingestion can be enabled/disabled per repo."""


@scenario(
    "../repository_discovery.feature",
    "Listing active repositories for ingestion",
)
def test_list_active_repos() -> None:
    """Behavioural test: listing respects ingestion_enabled flag."""


@pytest.fixture
def discovery_context(tmp_path: Path) -> typ.Iterator[DiscoveryContext]:
    """Provision a fresh database for each scenario."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'discovery.db'}")

    async def _init() -> None:
        await init_bronze_storage(engine)
        await init_silver_storage(engine)
        await init_catalogue_storage(engine)

    asyncio.run(_init())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    importer = CatalogueImporter(
        session_factory, estate_key="bdd", estate_name="BDD Estate"
    )
    service = RepositoryRegistryService(session_factory, session_factory)

    yield {
        "session_factory": session_factory,
        "importer": importer,
        "service": service,
    }

    asyncio.run(engine.dispose())


@given("a fresh database")
def fresh_database(discovery_context: DiscoveryContext) -> None:
    """Validate the discovery context was initialised."""
    assert "session_factory" in discovery_context


@given(parsers.parse('the catalogue at "{path}" is imported'))
def import_catalogue(discovery_context: DiscoveryContext, path: str) -> None:
    """Import the catalogue file."""
    catalogue_path = Path(path)
    assert catalogue_path.exists(), f"Catalogue file not found: {path}"

    async def _import() -> None:
        importer = discovery_context["importer"]
        await importer.import_path(catalogue_path, commit_sha="bdd-test")

    asyncio.run(_import())


@given("the repository registry syncs from catalogue")
@when("the repository registry syncs from catalogue")
def sync_registry(discovery_context: DiscoveryContext) -> None:
    """Run the registry sync from catalogue."""

    async def _sync() -> SyncResult:
        service = discovery_context["service"]
        return await service.sync_from_catalogue("bdd")

    discovery_context["sync_result"] = asyncio.run(_sync())


@when(parsers.parse('repository "{slug}" is removed from catalogue'))
def remove_from_catalogue(discovery_context: DiscoveryContext, slug: str) -> None:
    """Remove a repository from the catalogue database."""
    owner, name = slug.split("/")

    async def _remove() -> None:
        async with discovery_context["session_factory"]() as session, session.begin():
            repo = await session.scalar(
                select(RepositoryRecord).where(
                    RepositoryRecord.owner == owner,
                    RepositoryRecord.name == name,
                )
            )
            if repo:
                await session.delete(repo)

    asyncio.run(_remove())


@given(parsers.parse('ingestion is disabled for "{slug}"'))
@when(parsers.parse('ingestion is disabled for "{slug}"'))
def disable_ingestion(discovery_context: DiscoveryContext, slug: str) -> None:
    """Disable ingestion for a repository."""
    owner, name = slug.split("/")

    async def _disable() -> None:
        service = discovery_context["service"]
        await service.disable_ingestion(owner, name)

    asyncio.run(_disable())


@when(parsers.parse('ingestion is enabled for "{slug}"'))
def enable_ingestion(discovery_context: DiscoveryContext, slug: str) -> None:
    """Enable ingestion for a repository."""
    owner, name = slug.split("/")

    async def _enable() -> None:
        service = discovery_context["service"]
        await service.enable_ingestion(owner, name)

    asyncio.run(_enable())


@when("listing active repositories for ingestion")
def list_active_repos(discovery_context: DiscoveryContext) -> None:
    """List all active repositories."""

    async def _list() -> list[RepositoryInfo]:
        service = discovery_context["service"]
        return await service.list_active_repositories()

    discovery_context["active_repos"] = asyncio.run(_list())


@then(parsers.parse('the Silver layer contains repository "{slug}"'))
def silver_contains_repo(discovery_context: DiscoveryContext, slug: str) -> None:
    """Verify the repository exists in Silver."""
    owner, name = slug.split("/")

    async def _check() -> None:
        async with discovery_context["session_factory"]() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == owner,
                    Repository.github_name == name,
                )
            )
            assert repo is not None, f"Repository {slug} not found in Silver"

    asyncio.run(_check())


@then(parsers.parse('repository "{slug}" has ingestion enabled'))
def repo_ingestion_enabled(discovery_context: DiscoveryContext, slug: str) -> None:
    """Verify the repository has ingestion enabled."""
    owner, name = slug.split("/")

    async def _check() -> None:
        async with discovery_context["session_factory"]() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == owner,
                    Repository.github_name == name,
                )
            )
            assert repo is not None, f"Repository {slug} not found"
            assert repo.ingestion_enabled is True, (
                f"Expected ingestion_enabled=True for {slug}"
            )

    asyncio.run(_check())


@then(parsers.parse('repository "{slug}" has ingestion disabled'))
def repo_ingestion_disabled(discovery_context: DiscoveryContext, slug: str) -> None:
    """Verify the repository has ingestion disabled."""
    owner, name = slug.split("/")

    async def _check() -> None:
        async with discovery_context["session_factory"]() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == owner,
                    Repository.github_name == name,
                )
            )
            assert repo is not None, f"Repository {slug} not found"
            assert repo.ingestion_enabled is False, (
                f"Expected ingestion_enabled=False for {slug}"
            )

    asyncio.run(_check())


@then(parsers.parse('repository "{slug}" still exists in Silver'))
def repo_still_exists(discovery_context: DiscoveryContext, slug: str) -> None:
    """Verify the repository still exists in Silver (was not deleted)."""
    owner, name = slug.split("/")

    async def _check() -> None:
        async with discovery_context["session_factory"]() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == owner,
                    Repository.github_name == name,
                )
            )
            assert repo is not None, f"Repository {slug} should still exist in Silver"

    asyncio.run(_check())


@then(parsers.parse('repository "{slug}" has documentation paths from catalogue'))
def repo_has_doc_paths(discovery_context: DiscoveryContext, slug: str) -> None:
    """Verify the repository has documentation paths from catalogue."""
    owner, name = slug.split("/")

    async def _check() -> None:
        async with discovery_context["session_factory"]() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == owner,
                    Repository.github_name == name,
                )
            )
            assert repo is not None, f"Repository {slug} not found"
            assert len(repo.documentation_paths) > 0, (
                f"Expected documentation_paths for {slug}"
            )
            # leynos/wildside should have docs/roadmap.md and docs/adr/
            assert "docs/roadmap.md" in repo.documentation_paths

    asyncio.run(_check())


@then(parsers.parse('the result includes "{slug}"'))
def result_includes_repo(discovery_context: DiscoveryContext, slug: str) -> None:
    """Verify the active repos list includes the slug."""
    active_repos = discovery_context.get("active_repos", [])
    slugs = {repo.slug for repo in active_repos}
    assert slug in slugs, f"Expected {slug} in active repos, got {slugs}"


@then(parsers.parse('the result excludes "{slug}"'))
def result_excludes_repo(discovery_context: DiscoveryContext, slug: str) -> None:
    """Verify the active repos list excludes the slug."""
    active_repos = discovery_context.get("active_repos", [])
    slugs = {repo.slug for repo in active_repos}
    assert slug not in slugs, f"Expected {slug} not in active repos"
