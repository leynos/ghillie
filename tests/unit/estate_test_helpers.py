"""Reusable doubles and builders for estate-management tests.

Route-registration tests need the port registered but never call most of its
methods, so :class:`EmptyEstateManagement` keeps one empty double instead of
every test module repeating the five-method signature. The HTTP and service
suites share :class:`FakeEstateManagement` and the database-backed builders
from the same module so each split test file starts from the same fixtures.

Exported builders
-----------------
``build_estate_client``
    Wrap a :class:`FakeEstateManagement` in a Falcon test client whose app has
    only the estate service wired in.
``build_registry``
    Construct a :class:`RepositoryRegistryService` over a test session factory,
    using the same factory for the catalogue and Silver stores.
``build_service``
    Construct the :class:`EstateManagementService` under test from a session
    factory and a registry.
``catalogue_document``
    Render a minimal valid catalogue YAML document with overridable component
    and repository names.
``import_catalogue``
    Import through the service with terse defaults, treating only ``None`` as
    "use the fixture document" so an explicit empty upload still reaches the
    importer.
``count_rows``
    Count every row in one catalogue table.

``NOW`` and ``DOCUMENTATION_PATHS`` provide the fixed timestamp and path
fixtures the doubles advertise.
"""

import dataclasses
import datetime as dt
import typing as typ

import falcon.testing
from sqlalchemy import func, select

from ghillie.api.app import AppDependencies, create_app
from ghillie.estate.models import (
    CatalogueImportRequest,
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


def _estate_page(
    items: tuple[EstateSummary, ...], page: PageRequest
) -> Page[EstateSummary]:
    """Build a single-page estate result for a port double."""
    return Page(
        items=items,
        limit=page.limit,
        offset=page.offset,
        has_more=False,
        next_offset=None,
    )


class EmptyEstateManagement:
    """Estate port double that returns an empty first page."""

    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]:
        """Return an empty page."""
        return _estate_page((), page)

    async def import_catalogue(
        self, estate_key: str, request: CatalogueImportRequest
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
        return _estate_page(self.estate_items, page)

    async def import_catalogue(
        self, estate_key: str, request: CatalogueImportRequest
    ) -> CatalogueImportSummary:
        """Record and return a fixed import summary."""
        self.imports.append({"estate_key": estate_key, **dataclasses.asdict(request)})
        return CatalogueImportSummary(
            estate_key=estate_key,
            commit_sha=request.commit_sha,
            state="succeeded",
            dry_run=request.dry_run,
            skipped=False,
            skipped_reason=None,
            registry_sync_required=not request.dry_run,
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


class _ImportOverrides(typ.TypedDict, total=False):
    """Per-test overrides for :func:`import_catalogue`'s defaults."""

    estate_key: str
    commit_sha: str
    estate_name: str | None
    dry_run: bool
    catalogue_yaml: str | None


async def import_catalogue(
    service: EstateManagementService,
    **overrides: typ.Unpack[_ImportOverrides],
) -> CatalogueImportSummary:
    """Import a catalogue through the service with terse test defaults."""
    # Only ``None`` means "use the fixture"; an explicitly empty upload must
    # reach the importer so rejection tests exercise the real validation path.
    catalogue_yaml = overrides.get("catalogue_yaml")
    document = catalogue_document() if catalogue_yaml is None else catalogue_yaml
    request = CatalogueImportRequest(
        catalogue_yaml=document,
        commit_sha=overrides.get("commit_sha", "c1"),
        estate_name=overrides.get("estate_name", "Demo"),
        dry_run=overrides.get("dry_run", False),
    )
    return await service.import_catalogue(overrides.get("estate_key", "demo"), request)


async def count_rows(
    session_factory: async_sessionmaker[AsyncSession],
    model: type[Estate] | type[ProjectRecord],
) -> int:
    """Count every row in a catalogue table."""
    async with session_factory() as session:
        return (await session.scalar(select(func.count()).select_from(model))) or 0
