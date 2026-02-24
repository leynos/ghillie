"""Unit tests for RepositoryRegistryService ingestion toggles."""

from __future__ import annotations

import dataclasses
import typing as typ

import pytest

from ghillie.registry import RepositoryNotFoundError
from tests.fixtures.specs import RepositoryCreateSpec

if typ.TYPE_CHECKING:
    from ghillie.registry import RepositoryRegistryService
    from tests.fixtures.specs import CreateRepoFn, FetchRepoFn


@dataclasses.dataclass(frozen=True, slots=True)
class IngestionToggleParams:
    """Parameters for ingestion toggle test cases."""

    initial_state: bool
    method_name: str
    expected_state: bool
    expect_change: bool


@pytest.mark.asyncio
async def test_enable_ingestion_returns_false_when_already_enabled(
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """enable_ingestion() returns False when already enabled."""
    await create_repo(
        "test-org", "test-repo", spec=RepositoryCreateSpec(ingestion_enabled=True)
    )
    changed = await registry_service.enable_ingestion("test-org", "test-repo")
    assert changed is False


@pytest.mark.asyncio
async def test_disable_ingestion_returns_false_when_already_disabled(
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """disable_ingestion() returns False when already disabled."""
    await create_repo(
        "test-org", "test-repo", spec=RepositoryCreateSpec(ingestion_enabled=False)
    )
    changed = await registry_service.disable_ingestion("test-org", "test-repo")
    assert changed is False


@pytest.mark.asyncio
async def test_enable_ingestion_raises_for_missing_repo(
    registry_service: RepositoryRegistryService,
) -> None:
    """enable_ingestion() raises RepositoryNotFoundError for missing repo."""
    with pytest.raises(
        RepositoryNotFoundError,
        match=r"^Repository not found: nonexistent/repo$",
    ):
        await registry_service.enable_ingestion("nonexistent", "repo")


@pytest.mark.asyncio
async def test_disable_ingestion_raises_for_missing_repo(
    registry_service: RepositoryRegistryService,
) -> None:
    """disable_ingestion() raises RepositoryNotFoundError for missing repo."""
    with pytest.raises(
        RepositoryNotFoundError,
        match=r"^Repository not found: nonexistent/repo$",
    ):
        await registry_service.disable_ingestion("nonexistent", "repo")


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
    create_repo: CreateRepoFn,
    fetch_repo: FetchRepoFn,
    registry_service: RepositoryRegistryService,
    params: IngestionToggleParams,
) -> None:
    """Enable/disable ingestion methods update the flag correctly."""
    await create_repo(
        "test-org",
        "test-repo",
        spec=RepositoryCreateSpec(ingestion_enabled=params.initial_state),
    )

    if params.method_name == "enable_ingestion":
        changed = await registry_service.enable_ingestion("test-org", "test-repo")
    else:
        changed = await registry_service.disable_ingestion("test-org", "test-repo")
    assert changed is params.expect_change

    repo = await fetch_repo("test-org", "test-repo")
    assert repo is not None
    assert repo.ingestion_enabled is params.expected_state
