"""Unit tests for RepositoryRegistryService listing/pagination."""

from __future__ import annotations

import dataclasses
import typing as typ

import pytest

from ghillie.registry.listing import NegativePaginationError
from tests.unit.conftest import RepositoryCreateSpec

if typ.TYPE_CHECKING:
    from ghillie.registry import RepositoryRegistryService
    from tests.unit.conftest import CreateRepoFn


@dataclasses.dataclass(frozen=True, slots=True)
class ListingFilteringParams:
    """List call parameters and expected results."""

    method_name: str
    expected_slugs: set[str]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        pytest.param(
            ListingFilteringParams(
                method_name="list_active_repositories",
                expected_slugs={"org/enabled-repo"},
            ),
            id="active_only",
        ),
        pytest.param(
            ListingFilteringParams(
                method_name="list_all_repositories",
                expected_slugs={"org/enabled-repo", "org/disabled-repo"},
            ),
            id="all",
        ),
    ],
)
async def test_list_repositories_filtering(
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
    params: ListingFilteringParams,
) -> None:
    """List methods filter correctly by ingestion status."""
    await create_repo(
        "org", "enabled-repo", spec=RepositoryCreateSpec(ingestion_enabled=True)
    )
    await create_repo(
        "org", "disabled-repo", spec=RepositoryCreateSpec(ingestion_enabled=False)
    )

    method = getattr(registry_service, params.method_name)
    repos = await method()
    slugs = {repo.slug for repo in repos}
    assert slugs == params.expected_slugs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        pytest.param(
            ListingFilteringParams(
                method_name="list_active_repositories",
                expected_slugs={"org/estate-a-repo-1", "org/estate-a-repo-2"},
            ),
            id="active_only",
        ),
        pytest.param(
            ListingFilteringParams(
                method_name="list_all_repositories",
                expected_slugs={"org/estate-a-repo-1", "org/estate-a-repo-2"},
            ),
            id="all",
        ),
    ],
)
async def test_list_repositories_filters_by_estate_id(
    create_estates: tuple[str, str],
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
    params: ListingFilteringParams,
) -> None:
    """List methods filter by estate_id correctly."""
    estate_a_id, estate_b_id = create_estates

    await create_repo(
        "org",
        "estate-a-repo-1",
        spec=RepositoryCreateSpec(estate_id=estate_a_id, ingestion_enabled=True),
    )
    await create_repo(
        "org",
        "estate-a-repo-2",
        spec=RepositoryCreateSpec(estate_id=estate_a_id, ingestion_enabled=True),
    )
    await create_repo(
        "org",
        "estate-b-repo-1",
        spec=RepositoryCreateSpec(estate_id=estate_b_id, ingestion_enabled=True),
    )

    method = getattr(registry_service, params.method_name)
    repos = await method(estate_id=estate_a_id)
    slugs = {repo.slug for repo in repos}
    assert slugs == params.expected_slugs
    assert all(repo.estate_id == estate_a_id for repo in repos)


@pytest.mark.asyncio
async def test_list_all_repositories_supports_pagination(
    create_repo: CreateRepoFn,
    registry_service: RepositoryRegistryService,
) -> None:
    """Pagination returns stable pages in owner/name order."""
    await create_repo("b-org", "repo-1")
    await create_repo("a-org", "repo-2")
    await create_repo("a-org", "repo-1")
    await create_repo("c-org", "repo-0")

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
async def test_list_repositories_rejects_negative_limit(
    registry_service: RepositoryRegistryService,
) -> None:
    """Negative limits are rejected early."""
    with pytest.raises(NegativePaginationError, match="must be non-negative"):
        await registry_service.list_all_repositories(limit=-1)


@pytest.mark.asyncio
async def test_list_repositories_rejects_negative_offset(
    registry_service: RepositoryRegistryService,
) -> None:
    """Negative offsets are rejected early."""
    with pytest.raises(NegativePaginationError, match="must be non-negative"):
        await registry_service.list_all_repositories(offset=-1)
