"""Obligation O2: pagination completeness.

For every repository count from zero to twenty-six, every page limit in 1..10,
and every ingestion filter, walking the pages must visit each matching
repository exactly once in the order a single unpaged query returns. The
expected order comes from the database, never from Python ``sorted()``.
"""

import typing as typ

import pytest
from sqlalchemy import select

from ghillie.catalogue.storage import Estate
from ghillie.estate.models import CatalogueImportRequest, RepositoryQuery
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.estate.service import EstateManagementService
    from ghillie.registry.service import RepositoryRegistryService

_ESTATE_KEY = "pagination"
_REPOSITORY_COUNT = 26
_FILTERS = (None, True, False)
_LIMITS = range(1, 11)

# The exhaustive walk and its py-pglite fixture start-up both exceed the
# suite's 30-second default when the host is loaded, so this module opts into
# the longer budget the plan already reserves for database-heavy runs.
pytestmark = pytest.mark.timeout(120)


_CATALOGUE = """
version: 1
projects:
  - key: alpha
    name: Alpha
    components:
      - key: alpha-api
        name: Alpha API
        type: service
        lifecycle: active
        repository:
          owner: seed
          name: seed
          default_branch: main
"""


async def _import_seed(service: EstateManagementService) -> None:
    """Import the seed catalogue so the estate exists."""
    await service.import_catalogue(
        _ESTATE_KEY,
        CatalogueImportRequest(
            catalogue_yaml=_CATALOGUE,
            commit_sha="seed",
            estate_name="Pagination",
        ),
    )


async def _seed_estate(
    service: EstateManagementService,
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Import a catalogue so the estate exists, then return its identifier."""
    await _import_seed(service)
    async with session_factory() as session:
        estate = await session.scalar(select(Estate))
    assert estate is not None, "catalogue import should create an estate"
    return estate.id


async def _add_repository(
    session_factory: async_sessionmaker[AsyncSession],
    estate_id: str,
    *,
    index: int,
) -> None:
    """Insert one repository, alternating its ingestion flag."""
    async with session_factory() as session, session.begin():
        session.add(
            Repository(
                estate_id=estate_id,
                github_owner="org",
                github_name=f"repo-{index:02d}",
                default_branch="main",
                ingestion_enabled=index % 2 == 0,
            )
        )


async def _expected_slugs(
    registry: RepositoryRegistryService,
    estate_id: str,
    *,
    ingestion_enabled: bool | None,
) -> list[str]:
    """Read the expected order from one unpaged database query."""
    repositories = await registry.list_all_repositories(estate_id)
    return [
        repo.slug
        for repo in repositories
        if ingestion_enabled is None or repo.ingestion_enabled is ingestion_enabled
    ]


async def _walk_pages(
    service: EstateManagementService,
    *,
    ingestion_enabled: bool | None,
    limit: int,
    expected: list[str],
) -> None:
    """Walk every page and compare the visit order with the unpaged query."""
    visited: list[str] = []
    offset = 0
    while True:
        page = await service.list_repositories(
            _ESTATE_KEY,
            RepositoryQuery(
                ingestion_enabled=ingestion_enabled,
                limit=limit,
                offset=offset,
            ),
        )
        assert page.limit == limit, "page should echo the requested limit"
        assert page.offset == offset, "page should echo the requested offset"
        assert len(page.items) <= limit, "page should not exceed the requested limit"
        visited.extend(repo.slug for repo in page.items)

        if not page.has_more:
            assert page.next_offset is None, "final page should not offer a next offset"
            break

        next_offset = page.next_offset
        assert next_offset is not None, "more results should give a next offset"
        assert next_offset == offset + limit, "next offset should advance by one page"
        assert len(page.items) == limit, "a full page should contain the limit"
        offset = next_offset

    assert visited == expected, "paging should cover the same repositories in order"

    past_end = await service.list_repositories(
        _ESTATE_KEY,
        RepositoryQuery(
            ingestion_enabled=ingestion_enabled,
            limit=limit,
            offset=len(expected) + 7,
        ),
    )
    assert past_end.items == (), "offset past the end should return no items"
    assert past_end.has_more is False, "past the end should report no more"
    assert past_end.next_offset is None, "past the end should have no next offset"


async def _walk_every_limit(
    service: EstateManagementService,
    *,
    ingestion_enabled: bool | None,
    expected: list[str],
) -> None:
    """Walk the pages for every supported limit under one expected order."""
    for limit in _LIMITS:
        await _walk_pages(
            service,
            ingestion_enabled=ingestion_enabled,
            limit=limit,
            expected=expected,
        )


async def _walk_every_filter(
    service: EstateManagementService,
    registry: RepositoryRegistryService,
    estate_id: str,
) -> None:
    """Cover every ingestion filter for the repositories inserted so far."""
    for ingestion_enabled in _FILTERS:
        expected = await _expected_slugs(
            registry, estate_id, ingestion_enabled=ingestion_enabled
        )
        await _walk_every_limit(
            service,
            ingestion_enabled=ingestion_enabled,
            expected=expected,
        )


@pytest.mark.asyncio
async def test_walking_pages_visits_each_repository_exactly_once(
    service: EstateManagementService,
    registry: RepositoryRegistryService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Exhaustively walks 780 count, filter, and limit combinations."""
    estate_id = await _seed_estate(service, session_factory)

    # Cover ``N == 0`` inside the matrix so every filter and limit sees an
    # empty registry before any repository exists.
    await _walk_every_filter(service, registry, estate_id)

    for index in range(_REPOSITORY_COUNT):
        await _add_repository(session_factory, estate_id, index=index)
        await _walk_every_filter(service, registry, estate_id)


@pytest.mark.asyncio
async def test_first_page_of_an_empty_registry_is_empty(
    service: EstateManagementService,
) -> None:
    """``N == 0`` is covered directly, before any repository is inserted."""
    await _import_seed(service)

    page = await service.list_repositories(
        _ESTATE_KEY, RepositoryQuery(limit=10, offset=0)
    )

    assert page.items == (), "empty registry should list no repositories"
    assert page.has_more is False, "empty registry should report no further pages"
    assert page.next_offset is None, "empty registry should have no next offset"
