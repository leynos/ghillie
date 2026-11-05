"""Listing, synchronization, and toggle behaviour for the estate service.

Catalogue-import behaviour, including every translation of an importer
failure, lives in ``test_estate_service.py``. These tests cover the read paths
and the registry-backed mutations that share the same error vocabulary.
"""

import typing as typ

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from ghillie.estate.errors import (
    EstateConflictError,
    EstateNotFoundError,
    InvalidPaginationError,
    RegistrySyncFailedError,
    RepositoryNotFoundError,
    StorageUnavailableError,
)
from ghillie.estate.models import MAX_PAGE_OFFSET, PageRequest, RepositoryQuery
from ghillie.registry.errors import ESTATE_NOT_FOUND_REASON, RegistrySyncError
from ghillie.registry.service import RepositoryRegistryService
from tests.helpers.femtologging_capture import capture_femto_logs
from tests.unit.estate_test_helpers import catalogue_document, import_catalogue

if typ.TYPE_CHECKING:
    from ghillie.estate.service import EstateManagementService
    from tests.helpers.femtologging_capture import FemtoLogCapture

_ESTATE_KEY = "demo"
_OWNER = "org"
_REPO_NAME = "alpha"


# ---------------------------------------------------------------------------
# list_estates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_estates_pages_in_key_order(
    service: EstateManagementService,
) -> None:
    """The page envelope reports whether another page exists."""
    await import_catalogue(
        service,
        estate_key="beta",
        commit_sha="b1",
        catalogue_yaml=catalogue_document(component_key="beta-api", repo_name="beta"),
    )
    await import_catalogue(service, estate_key="alpha", commit_sha="a1")

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
    await import_catalogue(service, commit_sha="c1")

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
        (10, MAX_PAGE_OFFSET + 1, "offset"),
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
    await import_catalogue(service)

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
    await import_catalogue(service)

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
    await import_catalogue(service)

    async def _missing(
        _self: RepositoryRegistryService,
        estate_key: str,
        *,
        dry_run: bool = False,
    ) -> typ.Never:
        raise RegistrySyncError(estate_key, ESTATE_NOT_FOUND_REASON)

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
    await import_catalogue(service)

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


def _mutation_lines(logs: FemtoLogCapture, operation: str) -> list[str]:
    """Return the captured mutation records for one operation."""
    return [record.message for record in logs.records if operation in record.message]


@pytest.mark.asyncio
async def test_sync_registry_logs_one_terminal_record_when_it_succeeds(
    service: EstateManagementService,
) -> None:
    """D21: a successful sync emits exactly one terminal record."""
    await import_catalogue(service)

    with capture_femto_logs("ghillie.estate.service") as logs:
        await service.sync_registry(_ESTATE_KEY, dry_run=False)
        logs.wait_for_timeout()

    lines = _mutation_lines(logs, "estate.registry-sync")
    assert len(lines) == 1, "a successful sync should log exactly one record"
    assert "outcome=succeeded" in lines[0], "the record should name the outcome"
    assert "created=1" in lines[0], "the record should report the created count"
    assert "duration_ms=" in lines[0], "the record should report its duration"


@pytest.mark.asyncio
async def test_sync_registry_logs_one_terminal_record_when_it_fails(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D21: a failed sync logs one terminal record with its error class."""
    await import_catalogue(service)

    async def _fail(
        _self: RepositoryRegistryService,
        estate_key: str,
        *,
        dry_run: bool = False,
    ) -> typ.Never:
        raise RegistrySyncError(estate_key, "Database error during sync") from (
            IntegrityError("INSERT", {}, Exception("duplicate"))
        )

    monkeypatch.setattr(RepositoryRegistryService, "sync_from_catalogue", _fail)

    with capture_femto_logs("ghillie.estate.service") as logs:
        with pytest.raises(EstateConflictError):
            await service.sync_registry(_ESTATE_KEY, dry_run=False)
        logs.wait_for_timeout()

    lines = _mutation_lines(logs, "estate.registry-sync")
    assert len(lines) == 1, "a failed sync should log exactly one record"
    assert "outcome=failed" in lines[0], "the record should name the failure"
    assert "error=EstateConflictError" in lines[0], "the record should name the error"


@pytest.mark.asyncio
async def test_sync_registry_logs_a_missing_estate_as_a_failed_attempt(
    service: EstateManagementService,
) -> None:
    """D21: a sync for an unknown estate still produces one terminal record."""
    with capture_femto_logs("ghillie.estate.service") as logs:
        with pytest.raises(EstateNotFoundError):
            await service.sync_registry("missing", dry_run=False)
        logs.wait_for_timeout()

    lines = _mutation_lines(logs, "estate.registry-sync")
    assert len(lines) == 1, "a missing estate should log exactly one record"
    assert "outcome=failed" in lines[0], "the record should name the failure"
    assert "error=EstateNotFoundError" in lines[0], "the record should name the error"


# ---------------------------------------------------------------------------
# list_repositories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_repositories_filters_by_ingestion_state(
    service: EstateManagementService,
) -> None:
    """The repository listing honours the ingestion filter."""
    await import_catalogue(service)
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
@pytest.mark.parametrize(
    "query",
    [
        RepositoryQuery(limit=0, offset=0),
        RepositoryQuery(limit=10, offset=MAX_PAGE_OFFSET + 1),
    ],
)
async def test_list_repositories_rejects_invalid_pagination(
    service: EstateManagementService,
    query: RepositoryQuery,
) -> None:
    """Bad limits and oversized offsets are rejected before the estate lookup."""
    with pytest.raises(InvalidPaginationError):
        await service.list_repositories("missing", query)


@pytest.mark.asyncio
async def test_list_repositories_queries_the_registry_silver_store(
    service: EstateManagementService,
    registry: RepositoryRegistryService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listing delegates to the registry, which owns the Silver factory.

    Passing the catalogue factory to the Silver query would read the wrong
    database whenever the two stores are deployed separately.
    """
    await import_catalogue(service)
    calls: list[tuple[str | None, bool | None, int | None, int | None]] = []

    async def _list(
        estate_id: str | None = None,
        *,
        ingestion_enabled: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[typ.Never]:
        calls.append((estate_id, ingestion_enabled, limit, offset))
        return []

    monkeypatch.setattr(registry, "list_repositories", _list)

    page = await service.list_repositories(
        _ESTATE_KEY, RepositoryQuery(limit=5, offset=1)
    )

    assert page.items == (), "delegated empty page should stay empty"
    assert len(calls) == 1, "listing should delegate exactly once"
    estate_id, ingestion_enabled, limit, offset = calls[0]
    assert estate_id, "registry listing should receive the resolved estate id"
    assert ingestion_enabled is None, "no filter should be forwarded"
    assert (limit, offset) == (6, 1), "the over-fetch limit should be forwarded"


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
    await import_catalogue(service)
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
async def test_set_ingestion_escapes_a_hostile_repository_name(
    service: EstateManagementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newline in the repository name cannot forge a second log line."""

    async def _changed(_owner: str, _name: str, *, enabled: bool) -> bool:
        return True

    monkeypatch.setattr(service, "_toggle", _changed)
    hostile = "alpha\nestate.set-ingestion outcome=succeeded"

    with capture_femto_logs("ghillie.estate.service") as logs:
        await service.set_ingestion(_OWNER, hostile, enabled=False)
        logs.wait_for_timeout()

    toggle_lines = [
        record.message
        for record in logs.records
        if "estate.set-ingestion" in record.message
    ]
    assert toggle_lines, "the toggle should log one mutation line"
    assert all("\n" not in message for message in toggle_lines), (
        "the toggle record must stay on one line"
    )
    assert any("\\n" in message for message in toggle_lines), (
        "the control character should be visible as an escape"
    )


@pytest.mark.asyncio
async def test_set_ingestion_logs_one_terminal_record_when_it_fails(
    service: EstateManagementService,
) -> None:
    """D21: a failed toggle logs one terminal record with its error class."""
    with capture_femto_logs("ghillie.estate.service") as logs:
        with pytest.raises(RepositoryNotFoundError):
            await service.set_ingestion(_OWNER, "missing", enabled=True)
        logs.wait_for_timeout()

    lines = _mutation_lines(logs, "estate.set-ingestion")
    assert len(lines) == 1, "a failed toggle should log exactly one record"
    assert "outcome=failed" in lines[0], "the record should name the failure"
    assert "error=RepositoryNotFoundError" in lines[0], (
        "the record should name the error"
    )


@pytest.mark.asyncio
async def test_set_ingestion_logs_one_terminal_record_for_an_unexpected_error(
    service: EstateManagementService,
    registry: RepositoryRegistryService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D21: an unexpected toggle failure is recorded once and re-raised.

    ``set_ingestion`` translates the two failures it understands. Any other
    exception must still leave one terminal record, because a direct service
    caller has no HTTP catch-all to log it, and the exception must reach that
    caller unchanged.
    """

    async def _fail(_owner: str, _name: str) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(registry, "enable_ingestion", _fail)

    with capture_femto_logs("ghillie.estate.service") as logs:
        with pytest.raises(RuntimeError, match="boom"):
            await service.set_ingestion(_OWNER, _REPO_NAME, enabled=True)
        logs.wait_for_timeout()

    lines = _mutation_lines(logs, "estate.set-ingestion")
    assert len(lines) == 1, "an unexpected failure should log exactly one record"
    assert "outcome=failed" in lines[0], "the record should name the failure"
    assert "error=RuntimeError" in lines[0], "the record should name the error"


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
