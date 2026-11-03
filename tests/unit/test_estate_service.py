"""Application service behaviour for estate management.

Every underlying failure type is translated at this boundary. HTTP and CLI
adapters therefore see only :mod:`ghillie.estate.errors`, which keeps the error
contract independent of SQLAlchemy and registry internals.
"""

import asyncio
import typing as typ

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import (
    IntegrityError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)

from ghillie.catalogue.importer import CatalogueImporter, CatalogueImportResult
from ghillie.catalogue.storage import Estate, ProjectRecord
from ghillie.catalogue.validation import CatalogueValidationError
from ghillie.estate.errors import (
    CatalogueRejectedError,
    EstateConflictError,
    EstateNotFoundError,
    InvalidEstateKeyError,
    InvalidPaginationError,
    RegistrySyncFailedError,
    RepositoryNotFoundError,
    StorageUnavailableError,
)
from ghillie.estate.models import (
    CatalogueImportSummary,
    PageRequest,
    RepositoryQuery,
)
from ghillie.estate.service import EstateManagementService
from ghillie.registry.errors import RegistrySyncError
from ghillie.registry.service import RepositoryRegistryService

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_ESTATE_KEY = "demo"
_OWNER = "org"
_REPO_NAME = "alpha"


def _catalogue(
    *,
    component_key: str = "alpha-api",
    repo_owner: str = _OWNER,
    repo_name: str = _REPO_NAME,
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


@pytest.fixture
def registry(
    session_factory: async_sessionmaker[AsyncSession],
) -> RepositoryRegistryService:
    """Build a registry service over the shared test database."""
    return RepositoryRegistryService(session_factory, session_factory)


@pytest.fixture
def service(
    session_factory: async_sessionmaker[AsyncSession],
    registry: RepositoryRegistryService,
) -> EstateManagementService:
    """Build the service under test."""
    return EstateManagementService(session_factory, registry=registry)


async def _import(  # noqa: PLR0913 - keyword defaults keep each test call terse.
    service: EstateManagementService,
    *,
    estate_key: str = _ESTATE_KEY,
    commit_sha: str = "c1",
    estate_name: str | None = "Demo",
    dry_run: bool = False,
    catalogue_yaml: str | None = None,
) -> CatalogueImportSummary:
    return await service.import_catalogue(
        estate_key,
        catalogue_yaml=catalogue_yaml or _catalogue(),
        commit_sha=commit_sha,
        estate_name=estate_name,
        dry_run=dry_run,
    )


async def _count(
    session_factory: async_sessionmaker[AsyncSession],
    model: type[Estate] | type[ProjectRecord],
) -> int:
    async with session_factory() as session:
        return (await session.scalar(select(func.count()).select_from(model))) or 0


# ---------------------------------------------------------------------------
# import_catalogue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_creates_estate_and_reports_counts(
    service: EstateManagementService,
) -> None:
    """A first import reports what it created and asks for a registry sync."""
    summary = await _import(service)

    assert summary.estate_key == _ESTATE_KEY, "estate key should match the import"
    assert summary.commit_sha == "c1", "commit sha should be c1"
    assert summary.state == "succeeded", "import should succeed"
    assert summary.dry_run is False, "import should not be a dry run"
    assert summary.skipped is False, "import should not be skipped"
    assert summary.skipped_reason is None, "skipped reason should be empty"
    assert summary.registry_sync_required is True, "registry sync should be required"
    assert (summary.projects.created, summary.projects.updated) == (1, 0), (
        "projects should report one created"
    )
    assert (summary.components.created, summary.components.updated) == (1, 0), (
        "components should report one created"
    )
    assert (summary.repositories.created, summary.repositories.updated) == (1, 0), (
        "repositories should report one created"
    )
    assert (summary.edges.created, summary.edges.updated) == (0, 0), (
        "edges should report no changes"
    )


@pytest.mark.asyncio
async def test_import_is_idempotent_for_the_same_commit(
    service: EstateManagementService,
) -> None:
    """A repeated commit is skipped and does no work."""
    await _import(service, commit_sha="c1")

    summary = await _import(service, commit_sha="c1")

    assert summary.skipped is True, "repeated commit should be skipped"
    assert summary.skipped_reason == "commit_already_imported", (
        "skip reason should name the commit"
    )
    assert summary.registry_sync_required is False, "no registry sync required"
    assert summary.projects.created == 0, "repeated commit creates no projects"
    assert summary.components.created == 0, "repeated commit creates no components"
    assert summary.repositories.created == 0, "repeat creates no repositories"


@pytest.mark.asyncio
async def test_import_dry_run_leaves_no_catalogue_rows(
    service: EstateManagementService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A dry run reports counts after flushing, then rolls back."""
    summary = await _import(service, dry_run=True)

    assert summary.projects.created == 1, "dry run should report a project"
    assert summary.repositories.created == 1, "dry run should report a repository"
    assert summary.dry_run is True, "summary should be a dry run"
    assert summary.registry_sync_required is False, "no registry sync required"
    assert await _count(session_factory, Estate) == 0, "dry run should leave no estates"
    assert await _count(session_factory, ProjectRecord) == 0, (
        "dry run should leave no project rows"
    )


@pytest.mark.asyncio
async def test_import_uses_the_stored_name_when_none_is_supplied(
    service: EstateManagementService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """D18: a later import without a name does not rename the estate."""
    await _import(service, commit_sha="c1", estate_name="Demo Estate")

    await _import(service, commit_sha="c2", estate_name=None)

    async with session_factory() as session:
        estate = await session.scalar(select(Estate))
    assert estate is not None, "stored estate should exist"
    assert estate.name == "Demo Estate", "stored estate should keep its name"


@pytest.mark.asyncio
async def test_import_keeps_an_existing_description(
    service: EstateManagementService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """D18: catalogues carry no description, so an import must not clear one."""
    await _import(service, commit_sha="c1")
    async with session_factory() as session, session.begin():
        estate = await session.scalar(select(Estate))
        assert estate is not None, "stored estate should exist"
        estate.description = "Maintained by the platform team"

    await _import(service, commit_sha="c2", estate_name="Renamed")

    async with session_factory() as session:
        estate = await session.scalar(select(Estate))
    assert estate is not None, "stored estate should exist"
    assert estate.name == "Renamed", "import should rename the estate"
    assert estate.description == "Maintained by the platform team", (
        "import should keep the description"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("estate_key", ["", "-demo", ".demo", "demo/child"])
async def test_import_rejects_an_invalid_new_estate_key(
    service: EstateManagementService,
    estate_key: str,
) -> None:
    """D16: creating an estate requires the strict key pattern."""
    with pytest.raises(InvalidEstateKeyError):
        await _import(service, estate_key=estate_key)


@pytest.mark.asyncio
async def test_import_reports_catalogue_issues(
    service: EstateManagementService,
) -> None:
    """Invalid upload text becomes a catalogue rejection with issue codes."""
    with pytest.raises(CatalogueRejectedError) as raised:
        await _import(service, catalogue_yaml="version: [unclosed")

    assert raised.value.issues, "rejection should report issues"
    assert all(issue.code == "catalogue_schema" for issue in raised.value.issues), (
        "every issue should carry the catalogue code"
    )
    assert all(issue.message for issue in raised.value.issues), (
        "every issue should carry a message"
    )


@pytest.mark.asyncio
async def test_import_translates_validation_from_the_importer(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validation failure raised below the service is still a rejection."""

    async def _reject(
        _self: CatalogueImporter,
        _catalogue: object,
        *,
        commit_sha: str | None = None,
        dry_run: bool = False,
    ) -> CatalogueImportResult:
        raise CatalogueValidationError(["duplicate component key"])

    monkeypatch.setattr(CatalogueImporter, "import_catalogue", _reject)

    with pytest.raises(CatalogueRejectedError) as raised:
        await _import(service)

    assert raised.value.issues[0].message == "duplicate component key", (
        "validation should name the duplicate"
    )


@pytest.mark.asyncio
async def test_import_translates_an_integrity_error_to_conflict(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D17: a uniqueness violation is a conflict, not a storage outage."""

    async def _conflict(
        _self: CatalogueImporter,
        _catalogue: object,
        *,
        commit_sha: str | None = None,
        dry_run: bool = False,
    ) -> CatalogueImportResult:
        raise IntegrityError("INSERT", {}, Exception("duplicate"))

    monkeypatch.setattr(CatalogueImporter, "import_catalogue", _conflict)

    with pytest.raises(EstateConflictError):
        await _import(service)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT", {}, Exception("down")),
        InterfaceError("SELECT", {}, Exception("broken")),
        SQLAlchemyError("unexpected"),
    ],
)
async def test_import_translates_storage_errors(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
    error: SQLAlchemyError,
) -> None:
    """D17: connection and unexpected database failures are unavailable storage."""

    async def _fail(
        _self: CatalogueImporter,
        _catalogue: object,
        *,
        commit_sha: str | None = None,
        dry_run: bool = False,
    ) -> CatalogueImportResult:
        raise error

    monkeypatch.setattr(CatalogueImporter, "import_catalogue", _fail)

    with pytest.raises(StorageUnavailableError):
        await _import(service)


@pytest.mark.asyncio
async def test_import_lock_serializes_concurrent_imports(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D17: one estate is never imported twice at once in this process."""
    active = 0
    max_active = 0

    async def _slow_import(
        self: CatalogueImporter,
        _catalogue: object,
        *,
        commit_sha: str | None = None,
        dry_run: bool = False,
    ) -> CatalogueImportResult:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.05)
            return CatalogueImportResult(self.estate_key, commit_sha)
        finally:
            active -= 1

    monkeypatch.setattr(CatalogueImporter, "import_catalogue", _slow_import)

    await asyncio.gather(
        _import(service, commit_sha="c1"),
        _import(service, commit_sha="c2"),
    )

    assert max_active == 1, "imports should not overlap"


@pytest.mark.asyncio
async def test_estate_locks_are_not_retained_after_use(
    service: EstateManagementService,
) -> None:
    """D17: serialization does not leak one lock per key ever mentioned.

    An unauthenticated client can name any estate key, so a strong map would
    let it grow process memory indefinitely. The weak map must release an idle
    lock once the import block finishes.
    """
    await _import(service, estate_key="alpha")
    await _import(service, estate_key="beta")

    assert list(service._locks) == [], "idle locks should be released"


# ---------------------------------------------------------------------------
# list_estates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_estates_pages_in_key_order(
    service: EstateManagementService,
) -> None:
    """The page envelope reports whether another page exists."""
    await _import(
        service,
        estate_key="beta",
        commit_sha="b1",
        catalogue_yaml=_catalogue(component_key="beta-api", repo_name="beta"),
    )
    await _import(service, estate_key="alpha", commit_sha="a1")

    first = await service.list_estates(PageRequest(limit=1, offset=0))
    second = await service.list_estates(PageRequest(limit=1, offset=1))

    assert [item.key for item in first.items] == ["alpha"], "first page holds alpha"
    assert first.has_more is True, "first page should report more"
    assert first.next_offset == 1, "first page should point to offset 1"
    assert [item.key for item in second.items] == ["beta"], "last page holds beta"
    assert second.has_more is False, "last page should report no more"
    assert second.next_offset is None, "last page should have no next offset"


@pytest.mark.asyncio
async def test_list_estates_carries_the_latest_import(
    service: EstateManagementService,
) -> None:
    """A summary names the commit that was imported."""
    await _import(service, commit_sha="c1")

    page = await service.list_estates(PageRequest())

    [summary] = page.items
    assert summary.key == _ESTATE_KEY, "summary should carry the estate key"
    assert summary.name == "Demo", "summary should carry the estate name"
    assert summary.last_import_commit_sha == "c1", "summary should name the commit"
    assert summary.last_imported_at is not None, "summary should carry the import time"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limit", "offset", "field"),
    [
        (0, 0, "limit"),
        (501, 0, "limit"),
        (10, -1, "offset"),
    ],
)
async def test_list_estates_rejects_invalid_pagination(
    service: EstateManagementService,
    limit: int,
    offset: int,
    field: str,
) -> None:
    """Pagination input is validated before the database is queried."""
    with pytest.raises(InvalidPaginationError) as raised:
        await service.list_estates(PageRequest(limit=limit, offset=offset))

    assert raised.value.field == field, "error should name the offending field"


# ---------------------------------------------------------------------------
# sync_registry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_registry_reports_created_repositories(
    service: EstateManagementService,
) -> None:
    """A sync projects catalogue repositories into the registry."""
    await _import(service)

    summary = await service.sync_registry(_ESTATE_KEY, dry_run=False)

    assert summary.estate_key == _ESTATE_KEY, "summary should carry the estate key"
    assert summary.state == "succeeded", "sync should succeed"
    assert summary.dry_run is False, "sync should not be a dry run"
    assert summary.repositories_created == 1, "sync should create one repository"
    assert summary.repositories_updated == 0, "sync should update no repositories"
    assert summary.repositories_deactivated == 0, "sync should deactivate nothing"
    assert summary.repositories_conflicted == (), "sync should report no conflicts"
    assert summary.repositories_left_disabled == (), "sync should leave none disabled"
    assert summary.repositories_left_disabled_count == 0, "left disabled count is zero"


@pytest.mark.asyncio
async def test_sync_registry_dry_run_leaves_no_rows(
    service: EstateManagementService,
    registry: RepositoryRegistryService,
) -> None:
    """D20: a dry-run sync reports counts but persists nothing."""
    await _import(service)

    summary = await service.sync_registry(_ESTATE_KEY, dry_run=True)

    assert summary.repositories_created == 1, "dry run should report a creation"
    assert summary.dry_run is True, "summary should be a dry run"
    assert await registry.list_all_repositories() == [], (
        "dry run should persist no repositories"
    )


@pytest.mark.asyncio
async def test_sync_registry_requires_an_existing_estate(
    service: EstateManagementService,
) -> None:
    """An unknown estate is reported as not found."""
    with pytest.raises(EstateNotFoundError):
        await service.sync_registry("missing", dry_run=False)


@pytest.mark.asyncio
async def test_sync_registry_translates_a_not_found_reason(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registry that cannot find the estate maps to the same estate error."""
    await _import(service)

    async def _missing(
        _self: RepositoryRegistryService,
        estate_key: str,
        *,
        dry_run: bool = False,
    ) -> typ.Never:
        raise RegistrySyncError(estate_key, "Estate not found")

    monkeypatch.setattr(RepositoryRegistryService, "sync_from_catalogue", _missing)

    with pytest.raises(EstateNotFoundError):
        await service.sync_registry(_ESTATE_KEY, dry_run=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        (IntegrityError("INSERT", {}, Exception("duplicate")), EstateConflictError),
        (
            OperationalError("SELECT", {}, Exception("down")),
            StorageUnavailableError,
        ),
        (SQLAlchemyError("unexpected"), RegistrySyncFailedError),
    ],
)
async def test_sync_registry_translates_the_wrapped_cause(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
    cause: SQLAlchemyError,
    expected: type[Exception],
) -> None:
    """D17: the registry wraps SQL errors; the service inspects the cause."""
    await _import(service)

    async def _fail(
        _self: RepositoryRegistryService,
        estate_key: str,
        *,
        dry_run: bool = False,
    ) -> typ.Never:
        raise RegistrySyncError(estate_key, "Database error during sync") from cause

    monkeypatch.setattr(RepositoryRegistryService, "sync_from_catalogue", _fail)

    with pytest.raises(expected):
        await service.sync_registry(_ESTATE_KEY, dry_run=False)


# ---------------------------------------------------------------------------
# list_repositories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_repositories_filters_by_ingestion_state(
    service: EstateManagementService,
) -> None:
    """The repository listing honours the ingestion filter."""
    await _import(service)
    await service.sync_registry(_ESTATE_KEY, dry_run=False)
    await service.set_ingestion(_OWNER, _REPO_NAME, enabled=False)

    all_page = await service.list_repositories(
        _ESTATE_KEY, RepositoryQuery(limit=10, offset=0)
    )
    enabled_page = await service.list_repositories(
        _ESTATE_KEY, RepositoryQuery(ingestion_enabled=True, limit=10, offset=0)
    )
    disabled_page = await service.list_repositories(
        _ESTATE_KEY, RepositoryQuery(ingestion_enabled=False, limit=10, offset=0)
    )

    assert [repo.slug for repo in all_page.items] == [f"{_OWNER}/{_REPO_NAME}"], (
        "unfiltered listing should show the repository"
    )
    assert all_page.items[0].ingestion_enabled is False, "repository should be disabled"
    assert enabled_page.items == (), "filtered page should be empty"
    assert enabled_page.has_more is False, "filtered page should have no more"
    assert [repo.slug for repo in disabled_page.items] == [f"{_OWNER}/{_REPO_NAME}"], (
        "disabled listing should show the repository"
    )


@pytest.mark.asyncio
async def test_list_repositories_rejects_invalid_pagination(
    service: EstateManagementService,
) -> None:
    """Bad limits are rejected before the estate lookup."""
    with pytest.raises(InvalidPaginationError):
        await service.list_repositories("missing", RepositoryQuery(limit=0, offset=0))


@pytest.mark.asyncio
async def test_list_repositories_requires_an_existing_estate(
    service: EstateManagementService,
) -> None:
    """An unknown estate is reported as not found."""
    with pytest.raises(EstateNotFoundError):
        await service.list_repositories("missing", RepositoryQuery())


# ---------------------------------------------------------------------------
# set_ingestion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_ingestion_reports_each_transition(
    service: EstateManagementService,
) -> None:
    """The second identical toggle reports ``changed: false``."""
    await _import(service)
    await service.sync_registry(_ESTATE_KEY, dry_run=False)

    disabled = await service.set_ingestion(_OWNER, _REPO_NAME, enabled=False)
    repeated = await service.set_ingestion(_OWNER, _REPO_NAME, enabled=False)
    enabled = await service.set_ingestion(_OWNER, _REPO_NAME, enabled=True)

    assert disabled.ingestion_enabled is False, "toggle should disable ingestion"
    assert disabled.changed is True, "first toggle should change state"
    assert repeated.ingestion_enabled is False, "repeat should leave ingestion disabled"
    assert repeated.changed is False, "repeat toggle should change nothing"
    assert enabled.ingestion_enabled is True, "toggle should enable ingestion"
    assert enabled.changed is True, "enable toggle should change state"


@pytest.mark.asyncio
async def test_set_ingestion_translates_repository_not_found(
    service: EstateManagementService,
) -> None:
    """A missing repository is reported with its identity, not a slug string."""
    with pytest.raises(RepositoryNotFoundError) as raised:
        await service.set_ingestion(_OWNER, "missing", enabled=True)

    assert raised.value.owner == _OWNER, "error should carry the owner"
    assert raised.value.name == "missing", "error should carry the name"


@pytest.mark.asyncio
async def test_set_ingestion_translates_storage_errors(
    service: EstateManagementService,
    registry: RepositoryRegistryService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A database outage while toggling is unavailable storage."""

    async def _fail(_owner: str, _name: str) -> bool:
        raise OperationalError("UPDATE", {}, Exception("down"))

    monkeypatch.setattr(registry, "enable_ingestion", _fail)

    with pytest.raises(StorageUnavailableError):
        await service.set_ingestion(_OWNER, "missing", enabled=True)
