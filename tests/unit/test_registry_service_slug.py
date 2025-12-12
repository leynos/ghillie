"""Unit tests for RepositoryRegistryService slug lookups."""

from __future__ import annotations

import typing as typ

import pytest

from tests.unit.conftest import RepositoryCreateSpec

if typ.TYPE_CHECKING:
    from ghillie.registry import RepositoryRegistryService
    from tests.unit.conftest import CreateRepoFn


@pytest.mark.asyncio
async def test_get_repository_by_slug_returns_info(
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """get_repository_by_slug() returns RepositoryInfo for existing repo."""
    await create_repo(
        "test-org",
        "test-repo",
        spec=RepositoryCreateSpec(
            ingestion_enabled=True,
            documentation_paths=["docs/roadmap.md"],
        ),
    )

    repo = await registry_service.get_repository_by_slug("test-org/test-repo")

    assert repo is not None
    assert repo.owner == "test-org"
    assert repo.name == "test-repo"
    assert repo.slug == "test-org/test-repo"
    assert repo.ingestion_enabled is True
    assert "docs/roadmap.md" in repo.documentation_paths


@pytest.mark.asyncio
async def test_get_repository_by_slug_returns_none_for_missing(
    registry_service: RepositoryRegistryService,
) -> None:
    """get_repository_by_slug() returns None for missing repo."""
    repo = await registry_service.get_repository_by_slug("nonexistent/repo")
    assert repo is None


@pytest.mark.asyncio
async def test_get_repository_by_slug_returns_none_for_invalid_format(
    registry_service: RepositoryRegistryService,
) -> None:
    """get_repository_by_slug() returns None for slug without '/'."""
    repo = await registry_service.get_repository_by_slug("invalid-slug")
    assert repo is None
