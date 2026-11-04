"""Reusable doubles and builders for estate-management tests.

Route-registration tests need the port registered but never call most of its
methods, so :class:`EmptyEstateManagement` keeps one empty double instead of
every test module repeating the five-method signature. The HTTP and service
suites share :class:`FakeEstateManagement` and the database-backed builders
from the same module so each split test file starts from the same fixtures.
"""

import datetime as dt
import typing as typ

import falcon.testing
from sqlalchemy import func, select

from ghillie.api.app import AppDependencies, create_app
from ghillie.estate.models import (
    CatalogueImportSummary,
    CountSummary,
    EstateSummary,
    IngestionToggleOutcome,
    Page,
    PageRequest,
    RegistrySyncSummary,
    RepositoryPage,
    RepositoryQuery,
)
from ghillie.estate.service import EstateManagementService
from ghillie.registry.models import RepositoryInfo
from ghillie.registry.service import RepositoryRegistryService

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.catalogue.storage import Estate, ProjectRecord

__all__ = [
    "DOCUMENTATION_PATHS",
    "NOW",
    "EmptyEstateManagement",
    "FakeEstateManagement",
    "build_estate_client",
    "build_registry",
    "build_service",
    "catalogue_document",
    "count_rows",
    "import_catalogue",
]

NOW = dt.datetime(2024, 7, 7, 12, 0, tzinfo=dt.UTC)
DOCUMENTATION_PATHS = ("docs/", "README.md")


class EmptyEstateManagement:
    """Estate port double that returns an empty first page."""

    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]:
        """Return an empty page."""
        return Page(
            items=(),
            limit=page.limit,
            offset=page.offset,
            has_more=False,
            next_offset=None,
        )

    async def import_catalogue(  # noqa: PLR0913 - mirrors the port signature.
        self,
        estate_key: str,
        *,
        catalogue_yaml: str,
        commit_sha: str,
        estate_name: str | None,
        dry_run: bool,
    ) -> CatalogueImportSummary:
        """Raise because route-registration tests never import a catalogue."""
        raise NotImplementedError

    async def sync_registry(
        self, estate_key: str, *, dry_run: bool
    ) -> RegistrySyncSummary:
        """Raise because route-registration tests never synchronize the registry."""
        raise NotImplementedError

    async def list_repositories(
        self, estate_key: str, query: RepositoryQuery
    ) -> RepositoryPage:
        """Raise because route-registration tests never list repositories."""
        raise NotImplementedError

    async def set_ingestion(
        self, owner: str, name: str, *, enabled: bool
    ) -> IngestionToggleOutcome:
        """Raise because route-registration tests never toggle ingestion."""
        raise NotImplementedError


class FakeEstateManagement:
    """In-memory estate port double that records every call."""

    def __init__(self) -> None:
        """Build a double with one estate and one repository."""
        self.page_requests: list[PageRequest] = []
        self.repository_queries: list[RepositoryQuery] = []
        self.imports: list[dict[str, object]] = []
        self.syncs: list[dict[str, object]] = []
        self.toggles: list[dict[str, object]] = []
        self.estate_items: tuple[EstateSummary, ...] = (
            EstateSummary(
                key="demo",
                name="Demo",
                description="A demo estate",
                last_import_commit_sha="c1",
                last_imported_at=NOW,
            ),
        )
        self.repository_items: tuple[RepositoryInfo, ...] = (
            RepositoryInfo(
                id="repo-1",
                owner="org",
                name="alpha",
                default_branch="main",
                ingestion_enabled=True,
                documentation_paths=DOCUMENTATION_PATHS,
                estate_id="estate-1",
            ),
        )

    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]:
        """Return the configured estate page."""
        self.page_requests.append(page)
        return Page(
            items=self.estate_items,
            limit=page.limit,
            offset=page.offset,
            has_more=False,
            next_offset=None,
        )

    async def import_catalogue(  # noqa: PLR0913 - mirrors the port signature.
        self,
        estate_key: str,
        *,
        catalogue_yaml: str,
        commit_sha: str,
        estate_name: str | None,
        dry_run: bool,
    ) -> CatalogueImportSummary:
        """Record and return a fixed import summary."""
        self.imports.append(
            {
                "estate_key": estate_key,
                "catalogue_yaml": catalogue_yaml,
                "commit_sha": commit_sha,
                "estate_name": estate_name,
                "dry_run": dry_run,
            }
        )
        return CatalogueImportSummary(
            estate_key=estate_key,
            commit_sha=commit_sha,
            state="succeeded",
            dry_run=dry_run,
            skipped=False,
            skipped_reason=None,
            registry_sync_required=not dry_run,
            projects=CountSummary(created=1, updated=0, deleted=0),
            components=CountSummary(created=2, updated=0, deleted=1),
            repositories=CountSummary(created=1, updated=0, deleted=0),
            edges=CountSummary(created=1, updated=0, deleted=0),
        )

    async def sync_registry(
        self, estate_key: str, *, dry_run: bool
    ) -> RegistrySyncSummary:
        """Record and return a fixed sync summary."""
        self.syncs.append({"estate_key": estate_key, "dry_run": dry_run})
        return RegistrySyncSummary(
            estate_key=estate_key,
            state="succeeded",
            dry_run=dry_run,
            repositories_created=1,
            repositories_updated=2,
            repositories_deactivated=0,
            repositories_conflicted=("other/estate-repo",),
            repositories_left_disabled=("org/alpha",),
            repositories_left_disabled_count=1,
        )

    async def list_repositories(
        self, estate_key: str, query: RepositoryQuery
    ) -> RepositoryPage:
        """Record and return the configured repository page."""
        self.repository_queries.append(query)
        return RepositoryPage(
            estate_key=estate_key,
            items=self.repository_items,
            limit=query.limit,
            offset=query.offset,
            has_more=False,
            next_offset=None,
        )

    async def set_ingestion(
        self, owner: str, name: str, *, enabled: bool
    ) -> IngestionToggleOutcome:
        """Record and return a fixed toggle outcome."""
        self.toggles.append({"owner": owner, "name": name, "enabled": enabled})
        return IngestionToggleOutcome(
            owner=owner,
            name=name,
            ingestion_enabled=enabled,
            changed=True,
        )


def build_estate_client(service: FakeEstateManagement) -> falcon.testing.TestClient:
    """Build a client for an app with only the estate service configured."""
    return falcon.testing.TestClient(
        create_app(AppDependencies(estate_service=service))
    )


def build_registry(
    session_factory: async_sessionmaker[AsyncSession],
) -> RepositoryRegistryService:
    """Build a registry service over the shared test database."""
    return RepositoryRegistryService(session_factory, session_factory)


def build_service(
    session_factory: async_sessionmaker[AsyncSession],
    registry: RepositoryRegistryService,
) -> EstateManagementService:
    """Build the estate service under test."""
    return EstateManagementService(session_factory, registry=registry)


def catalogue_document(
    *,
    component_key: str = "alpha-api",
    repo_owner: str = "org",
    repo_name: str = "alpha",
) -> str:
    """Build a minimal valid catalogue document."""
    return f"""
version: 1
projects:
  - key: alpha
    name: Alpha
    components:
      - key: {component_key}
        name: Alpha API
        type: service
        lifecycle: active
        repository:
          owner: {repo_owner}
          name: {repo_name}
          default_branch: main
"""


async def import_catalogue(  # noqa: PLR0913 - keyword defaults keep each test call terse.
    service: EstateManagementService,
    *,
    estate_key: str = "demo",
    commit_sha: str = "c1",
    estate_name: str | None = "Demo",
    dry_run: bool = False,
    catalogue_yaml: str | None = None,
) -> CatalogueImportSummary:
    """Import a catalogue through the service with terse test defaults."""
    return await service.import_catalogue(
        estate_key,
        catalogue_yaml=catalogue_yaml or catalogue_document(),
        commit_sha=commit_sha,
        estate_name=estate_name,
        dry_run=dry_run,
    )


async def count_rows(
    session_factory: async_sessionmaker[AsyncSession],
    model: type[Estate] | type[ProjectRecord],
) -> int:
    """Count every row in a catalogue table."""
    async with session_factory() as session:
        return (await session.scalar(select(func.count()).select_from(model))) or 0
