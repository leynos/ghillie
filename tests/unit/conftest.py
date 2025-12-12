"""Unit-test fixtures for RepositoryRegistryService."""

from __future__ import annotations

import dataclasses
import typing as typ
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from ghillie.catalogue.storage import Estate
from ghillie.registry import RepositoryRegistryService
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the repository root directory."""
    return _find_repo_root(Path(__file__).resolve())


@pytest.fixture(scope="session")
def wildside_catalogue_path(repo_root: Path) -> Path:
    """Return the path to the example wildside catalogue file."""
    return repo_root / "examples" / "wildside-catalogue.yaml"


@dataclasses.dataclass(frozen=True, slots=True)
class RepositoryCreateSpec:
    """Fields used when creating Silver Repository rows in tests."""

    ingestion_enabled: bool = True
    default_branch: str = "main"
    estate_id: str | None = None
    catalogue_repository_id: str | None = None
    documentation_paths: list[str] | None = None


class CreateRepoFn(typ.Protocol):
    """Callable fixture for creating Silver repositories."""

    def __call__(
        self,
        owner: str,
        name: str,
        *,
        spec: RepositoryCreateSpec | None = None,
    ) -> cabc.Awaitable[None]:
        """Create a Silver repository row."""
        ...


class FetchRepoFn(typ.Protocol):
    """Callable fixture for fetching repositories."""

    def __call__(self, owner: str, name: str) -> cabc.Awaitable[Repository | None]:
        """Fetch a repository by owner/name."""
        ...


@pytest.fixture
def create_repo(session_factory: async_sessionmaker[AsyncSession]) -> CreateRepoFn:
    """Return a factory for creating test repositories."""

    async def _create(
        owner: str,
        name: str,
        *,
        spec: RepositoryCreateSpec | None = None,
    ) -> None:
        create_spec = spec or RepositoryCreateSpec()
        async with session_factory() as session, session.begin():
            repo = Repository(
                github_owner=owner,
                github_name=name,
                default_branch=create_spec.default_branch,
                ingestion_enabled=create_spec.ingestion_enabled,
                estate_id=create_spec.estate_id,
                catalogue_repository_id=create_spec.catalogue_repository_id,
                documentation_paths=create_spec.documentation_paths or [],
            )
            session.add(repo)

    return _create


@pytest.fixture
def fetch_repo(session_factory: async_sessionmaker[AsyncSession]) -> FetchRepoFn:
    """Return a factory for fetching repositories by owner/name."""

    async def _fetch(owner: str, name: str) -> Repository | None:
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
