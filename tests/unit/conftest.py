"""Shared unit-test fixtures."""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import typing as typ
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from ghillie.bronze import RawEventWriter
from ghillie.catalogue.storage import Estate
from ghillie.evidence import EvidenceBundleService
from ghillie.registry import RepositoryRegistryService
from ghillie.reporting.config import ReportingConfig
from ghillie.reporting.service import ReportingService, ReportingServiceDependencies
from ghillie.silver import RawEventTransformer
from ghillie.silver.storage import Repository
from ghillie.status import MockStatusModel
from tests.helpers.event_builders import commit_envelope

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.gold import Report


def _find_repo_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    msg = f"Failed to locate repository root (missing pyproject.toml) from: {start}"
    raise FileNotFoundError(msg)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the repository root directory."""
    return _find_repo_root(Path(__file__).resolve())


@pytest.fixture(scope="session")
def wildside_catalogue_path(repo_root: Path) -> Path:
    """Return the path to the example wildside catalogue file."""
    return repo_root / "examples" / "wildside-catalogue.yaml"


@dc.dataclass(frozen=True, slots=True)
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


# ---------------------------------------------------------------------------
# Reporting fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def reporting_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> ReportingService:
    """Return a configured ReportingService for testing."""
    deps = ReportingServiceDependencies(
        session_factory=session_factory,
        evidence_service=EvidenceBundleService(session_factory),
        status_model=MockStatusModel(),
    )
    return ReportingService(deps, config=ReportingConfig())


@pytest.fixture
def writer(
    session_factory: async_sessionmaker[AsyncSession],
) -> RawEventWriter:
    """Return a RawEventWriter for test data setup."""
    return RawEventWriter(session_factory)


@pytest.fixture
def transformer(
    session_factory: async_sessionmaker[AsyncSession],
) -> RawEventTransformer:
    """Return a RawEventTransformer for test data setup."""
    return RawEventTransformer(session_factory)


async def create_test_repository(
    session_factory: async_sessionmaker[AsyncSession],
    owner: str = "acme",
    name: str = "widget",
) -> str:
    """Create a test repository and return its ID."""
    async with session_factory() as session, session.begin():
        repo = Repository(
            github_owner=owner,
            github_name=name,
            default_branch="main",
            ingestion_enabled=True,
            estate_id="estate-1",
        )
        session.add(repo)
        await session.flush()
        return repo.id


@dc.dataclass(frozen=True, slots=True)
class RepositoryEventSpec:
    """Encapsulates test repository and event data for helper functions.

    Groups the four test-data parameters that are always passed together
    when setting up a repository with a commit event, reducing the
    parameter count of ``setup_test_repository_with_event``.

    .. note:: The name avoids the ``Test`` prefix so pytest does not
       attempt to collect this dataclass as a test class.
    """

    owner: str = "acme"
    name: str = "widget"
    commit_hash: str = "test001"
    commit_time: dt.datetime | None = None


async def get_repo_id(
    session_factory: async_sessionmaker[AsyncSession],
    owner: str = "acme",
    name: str = "widget",
) -> str:
    """Query repository by owner/name and return its ID."""
    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == owner,
                Repository.github_name == name,
            )
        )
        assert repo is not None, f"Repository {owner}/{name} not found"  # noqa: S101
        return repo.id


async def setup_test_repository_with_event(
    writer: RawEventWriter,
    transformer: RawEventTransformer,
    session_factory: async_sessionmaker[AsyncSession],
    spec: RepositoryEventSpec | None = None,
) -> str:
    """Ingest a commit event and return the repository ID.

    Creates a repository (via ingestion) with a single commit event,
    processes it through the transformer, and returns the resulting
    repository ID.

    Parameters
    ----------
    writer
        Raw event writer for ingesting the commit.
    transformer
        Raw event transformer for processing pending events.
    session_factory
        Async session factory for querying the repository.
    spec
        Test repository and event data.  Uses defaults (``acme/widget``,
        hash ``"test001"``, commit at 2024-07-05 10:00 UTC) when *None*.

    Returns
    -------
    str
        The Silver layer repository ID.

    """
    test_spec = spec or RepositoryEventSpec()
    effective_time = test_spec.commit_time or dt.datetime(
        2024, 7, 5, 10, 0, tzinfo=dt.UTC
    )
    repo_slug = f"{test_spec.owner}/{test_spec.name}"
    await writer.ingest(
        commit_envelope(
            repo_slug, test_spec.commit_hash, effective_time, "feat: test event"
        )
    )
    await transformer.process_pending()
    return await get_repo_id(session_factory, test_spec.owner, test_spec.name)


@pytest_asyncio.fixture
async def generated_report(
    session_factory: async_sessionmaker[AsyncSession],
    reporting_service: ReportingService,
    writer: RawEventWriter,
    transformer: RawEventTransformer,
) -> tuple[Report, str]:
    """Generate a standard test report and return (report, repo_id).

    Sets up standard test data:
    - repo_slug: acme/widget
    - window: 2024-07-01 to 2024-07-08
    - commit at 2024-07-05 10:00 UTC with hash "abc123"
    """
    repo_slug = "acme/widget"
    window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
    window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)
    commit_time = dt.datetime(2024, 7, 5, 10, 0, tzinfo=dt.UTC)

    await writer.ingest(
        commit_envelope(repo_slug, "abc123", commit_time, "feat: new feature")
    )
    await transformer.process_pending()

    repo_id = await get_repo_id(session_factory)

    report = await reporting_service.generate_report(
        repository_id=repo_id,
        window_start=window_start,
        window_end=window_end,
    )

    return report, repo_id
