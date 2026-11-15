"""Unit coverage for the estate persistence boundary.

The adapter is the only estate module that imports SQLAlchemy, so these tests
pin the classification it owns: every storage failure leaves as an error the
port documents, and a failure it does not recognise is re-raised unchanged.
"""

import typing as typ

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from ghillie.catalogue import queries
from ghillie.catalogue.models import Catalogue
from ghillie.estate import persistence
from ghillie.estate.errors import (
    EstateConflictError,
    EstateNotFoundError,
    RegistrySyncFailedError,
    RepositoryNotFoundError,
    StorageUnavailableError,
)
from ghillie.estate.models import RepositoryQuery
from ghillie.registry.errors import ESTATE_NOT_FOUND_REASON, RegistrySyncError
from ghillie.registry.errors import (
    RepositoryNotFoundError as RegistryRepositoryNotFoundError,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.catalogue.importer import CatalogueImporter
    from ghillie.registry.service import RepositoryRegistryService

_UNUSED_SESSION_FACTORY = typ.cast("async_sessionmaker[AsyncSession]", None)
_EMPTY_CATALOGUE = Catalogue(version=1, projects=[])


class _ImporterDouble:
    """Importer that records its call and then succeeds or raises."""

    def __init__(self, *, error: Exception | None = None) -> None:
        """Configure the double with the failure it should raise, if any."""
        self.error = error
        self.calls: list[tuple[object, str, bool]] = []

    async def import_catalogue(
        self, catalogue: object, *, commit_sha: str, dry_run: bool
    ) -> object:
        """Record the call, then raise or return a sentinel result."""
        self.calls.append((catalogue, commit_sha, dry_run))
        if self.error is not None:
            raise self.error
        return object()


class _RegistryDouble:
    """Registry double that records calls and raises its configured failure."""

    def __init__(self, *, error: Exception | None = None) -> None:
        """Configure the double with the failure it should raise, if any."""
        self.error = error
        self.calls: list[str] = []

    async def sync_from_catalogue(
        self, estate_key: str, *, dry_run: bool = False
    ) -> object:
        """Record the sync, then raise or return a sentinel result."""
        self.calls.append(f"sync:{estate_key}:{dry_run}")
        if self.error is not None:
            raise self.error
        return object()

    async def list_repositories(
        self,
        estate_id: str | None = None,
        *,
        ingestion_enabled: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[object]:
        """Record the listing, then raise or return no rows."""
        self.calls.append(f"list:{estate_id}:{ingestion_enabled}:{limit}:{offset}")
        if self.error is not None:
            raise self.error
        return []

    async def enable_ingestion(self, owner: str, name: str) -> bool:
        """Record the enable, then raise or report a change."""
        self.calls.append(f"enable:{owner}/{name}")
        if self.error is not None:
            raise self.error
        return True

    async def disable_ingestion(self, owner: str, name: str) -> bool:
        """Record the disable, then raise or report no change."""
        self.calls.append(f"disable:{owner}/{name}")
        if self.error is not None:
            raise self.error
        return False


def _importer(double: _ImporterDouble) -> CatalogueImporter:
    """Present an importer double as the adapter's parameter type."""
    return typ.cast("CatalogueImporter", double)


def _registry(double: _RegistryDouble) -> RepositoryRegistryService:
    """Present a registry double as the adapter's parameter type."""
    return typ.cast("RepositoryRegistryService", double)


@pytest.mark.asyncio
async def test_list_estates_translates_storage_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A catalogue read failure leaves as unavailable storage."""

    async def _fail(*_args: object, **_kwargs: object) -> typ.Never:
        """Fail the way an unreachable database does."""
        raise OperationalError("SELECT", {}, Exception("down"))

    monkeypatch.setattr(queries, "list_estates", _fail)

    with pytest.raises(StorageUnavailableError):
        await persistence.list_estates(_UNUSED_SESSION_FACTORY, limit=10, offset=0)


@pytest.mark.asyncio
async def test_get_estate_by_key_translates_storage_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed estate lookup leaves as unavailable storage."""

    async def _fail(*_args: object, **_kwargs: object) -> typ.Never:
        """Fail the way an unreachable database does."""
        raise SQLAlchemyError("unexpected")

    monkeypatch.setattr(queries, "get_estate_by_key", _fail)

    with pytest.raises(StorageUnavailableError):
        await persistence.get_estate_by_key(_UNUSED_SESSION_FACTORY, "demo")


@pytest.mark.asyncio
async def test_import_catalogue_passes_the_document_through() -> None:
    """The adapter forwards the parsed catalogue and its metadata unchanged."""
    importer = _ImporterDouble()

    result = await persistence.import_catalogue(
        _importer(importer), _EMPTY_CATALOGUE, commit_sha="c1", dry_run=True
    )

    assert result is not None, "the importer result should be returned"
    assert importer.calls == [(_EMPTY_CATALOGUE, "c1", True)], (
        "the call should be unchanged"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (IntegrityError("INSERT", {}, Exception("duplicate")), EstateConflictError),
        (SQLAlchemyError("unexpected"), StorageUnavailableError),
    ],
)
async def test_import_catalogue_translates_storage_failures(
    error: Exception,
    expected: type[Exception],
) -> None:
    """A rejected write is a conflict and any other SQL failure is an outage."""
    importer = _ImporterDouble(error=error)

    with pytest.raises(expected):
        await persistence.import_catalogue(
            _importer(importer), _EMPTY_CATALOGUE, commit_sha="c1", dry_run=False
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cause", "reason", "expected"),
    [
        (
            IntegrityError("INSERT", {}, Exception("duplicate")),
            "Database error during sync",
            EstateConflictError,
        ),
        (
            OperationalError("SELECT", {}, Exception("down")),
            "Database error during sync",
            StorageUnavailableError,
        ),
        (
            AttributeError("plain"),
            "Database error during sync",
            RegistrySyncFailedError,
        ),
        (None, ESTATE_NOT_FOUND_REASON, EstateNotFoundError),
    ],
)
async def test_sync_registry_translates_the_registry_failure(
    cause: Exception | None,
    reason: str,
    expected: type[Exception],
) -> None:
    """The wrapped cause, then the reported reason, decide the estate error."""
    error = RegistrySyncError("demo", reason)
    error.__cause__ = cause
    registry = _RegistryDouble(error=error)

    with pytest.raises(expected):
        await persistence.sync_registry(_registry(registry), "demo", dry_run=False)


@pytest.mark.asyncio
async def test_list_repositories_translates_storage_failures() -> None:
    """A Silver read failure leaves as unavailable storage."""
    registry = _RegistryDouble(error=OperationalError("SELECT", {}, Exception("down")))

    with pytest.raises(StorageUnavailableError):
        await persistence.list_repositories(
            _registry(registry), "estate-1", RepositoryQuery()
        )


@pytest.mark.asyncio
async def test_set_ingestion_selects_the_requested_state() -> None:
    """Enabling and disabling call their own registry method."""
    registry = _RegistryDouble()

    enabled = await persistence.set_ingestion(
        _registry(registry), "org", "alpha", enabled=True
    )
    disabled = await persistence.set_ingestion(
        _registry(registry), "org", "alpha", enabled=False
    )

    assert enabled is True, "enable should report the registry's answer"
    assert disabled is False, "disable should report the registry's answer"
    assert registry.calls == ["enable:org/alpha", "disable:org/alpha"], (
        "each state should reach its own registry method"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            RegistryRepositoryNotFoundError("org/alpha"),
            RepositoryNotFoundError,
        ),
        (OperationalError("UPDATE", {}, Exception("down")), StorageUnavailableError),
    ],
)
async def test_set_ingestion_translates_registry_failures(
    error: Exception,
    expected: type[Exception],
) -> None:
    """A missing row and an outage each leave as their estate error."""
    registry = _RegistryDouble(error=error)

    with pytest.raises(expected):
        await persistence.set_ingestion(
            _registry(registry), "org", "alpha", enabled=True
        )
