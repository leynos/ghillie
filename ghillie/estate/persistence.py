"""Persistence boundary for the estate-management service.

This is the only estate module that knows SQLAlchemy or the shape of a registry
failure. The service calls these functions instead of the catalogue query module
and the registry service directly, so every storage failure is classified here,
once, and leaves as an error :mod:`ghillie.estate.ports` already documents.
Hecate classifies the module as ``outbound_adapter``: the application service
may depend on it, and it depends only on the port and the modules that actually
reach a store.
"""

from __future__ import annotations

import typing as typ

from sqlalchemy.exc import (
    IntegrityError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)

from ghillie.catalogue import queries
from ghillie.estate.errors import (
    EstateConflictError,
    EstateNotFoundError,
    RegistrySyncFailedError,
    RepositoryNotFoundError,
    StorageUnavailableError,
)
from ghillie.registry.errors import ESTATE_NOT_FOUND_REASON, RegistrySyncError
from ghillie.registry.errors import (
    RepositoryNotFoundError as RegistryRepositoryNotFoundError,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.catalogue.importer import CatalogueImporter, CatalogueImportResult
    from ghillie.catalogue.models import Catalogue
    from ghillie.catalogue.queries import EstateRow
    from ghillie.estate.models import RepositoryQuery
    from ghillie.registry.models import RepositoryInfo, SyncResult
    from ghillie.registry.service import RepositoryRegistryService

STORAGE_MESSAGE = "storage is unavailable"
CONFLICT_MESSAGE = "the write conflicts with an existing record"
SYNC_FAILED_MESSAGE = "the registry sync failed"


async def list_estates(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int,
    offset: int,
) -> list[EstateRow]:
    """Return estates ordered by key, translating storage failures.

    Parameters
    ----------
    session_factory:
        Factory for async catalogue sessions.
    limit:
        Maximum number of rows to return.
    offset:
        Number of ordered rows to skip.

    Returns
    -------
    list[EstateRow]
        Estates in key order.

    Raises
    ------
    StorageUnavailableError
        If the catalogue database cannot be read.

    """
    try:
        return await queries.list_estates(session_factory, limit=limit, offset=offset)
    except SQLAlchemyError as exc:
        raise StorageUnavailableError(STORAGE_MESSAGE) from exc


async def get_estate_by_key(
    session_factory: async_sessionmaker[AsyncSession], estate_key: str
) -> EstateRow | None:
    """Return one estate by key, translating storage failures.

    Parameters
    ----------
    session_factory:
        Factory for async catalogue sessions.
    estate_key:
        Estate key to look up.

    Returns
    -------
    EstateRow or None
        The matching estate, or ``None`` when no estate has that key.

    Raises
    ------
    StorageUnavailableError
        If the catalogue database cannot be read.

    """
    try:
        return await queries.get_estate_by_key(session_factory, estate_key)
    except SQLAlchemyError as exc:
        raise StorageUnavailableError(STORAGE_MESSAGE) from exc


async def import_catalogue(
    importer: CatalogueImporter,
    catalogue: Catalogue,
    *,
    commit_sha: str,
    dry_run: bool,
) -> CatalogueImportResult:
    """Run the catalogue importer, translating its storage failures.

    A catalogue validation failure is not a storage failure, so it propagates
    unchanged for the service to translate into the port's error vocabulary.

    Parameters
    ----------
    importer:
        Importer bound to the estate being written.
    catalogue:
        Parsed catalogue to reconcile.
    commit_sha:
        Commit the catalogue was read from.
    dry_run:
        When true, reconcile inside a transaction and roll it back.

    Returns
    -------
    CatalogueImportResult
        The counts and skip state the importer produced.

    Raises
    ------
    EstateConflictError
        If a uniqueness constraint rejects the write.
    StorageUnavailableError
        If the catalogue database cannot be written.

    """
    try:
        return await importer.import_catalogue(
            catalogue,
            commit_sha=commit_sha,
            dry_run=dry_run,
        )
    except IntegrityError as exc:
        raise EstateConflictError(CONFLICT_MESSAGE) from exc
    except SQLAlchemyError as exc:
        raise StorageUnavailableError(STORAGE_MESSAGE) from exc


async def sync_registry(
    registry: RepositoryRegistryService,
    estate_key: str,
    *,
    dry_run: bool,
) -> SyncResult:
    """Project an estate's repositories into the registry.

    Parameters
    ----------
    registry:
        Registry collaborator that owns the Silver writes.
    estate_key:
        Key of the estate whose repositories should be synchronized.
    dry_run:
        When true, report the counts without persisting them.

    Returns
    -------
    SyncResult
        Counts, conflicts, and repositories left disabled by the sync.

    Raises
    ------
    EstateNotFoundError
        If the registry reports that the estate does not exist.
    EstateConflictError
        If a uniqueness constraint rejects the projection.
    RegistrySyncFailedError
        If a failure is neither a conflict nor a storage outage.
    StorageUnavailableError
        If the registry wraps a connection-level outage.

    """
    try:
        return await registry.sync_from_catalogue(estate_key, dry_run=dry_run)
    except RegistrySyncError as exc:
        raise _sync_error(estate_key, exc) from exc
    except IntegrityError as exc:
        raise EstateConflictError(CONFLICT_MESSAGE) from exc
    except SQLAlchemyError as exc:
        raise RegistrySyncFailedError(SYNC_FAILED_MESSAGE) from exc


async def list_repositories(
    registry: RepositoryRegistryService,
    estate_id: str,
    query: RepositoryQuery,
) -> list[RepositoryInfo]:
    """Return an estate's registered repositories from Silver.

    Parameters
    ----------
    registry:
        Registry collaborator that owns the Silver session factory.
    estate_id:
        Database identifier of the estate.
    query:
        Ingestion filter and the page size and offset to read.

    Returns
    -------
    list[RepositoryInfo]
        Repositories in the registry's order.

    Raises
    ------
    StorageUnavailableError
        If the registry database cannot be read.

    """
    try:
        return await registry.list_repositories(
            estate_id,
            ingestion_enabled=query.ingestion_enabled,
            limit=query.limit,
            offset=query.offset,
        )
    except SQLAlchemyError as exc:
        raise StorageUnavailableError(STORAGE_MESSAGE) from exc


async def set_ingestion(
    registry: RepositoryRegistryService,
    owner: str,
    name: str,
    *,
    enabled: bool,
) -> bool:
    """Set one repository's ingestion flag.

    Parameters
    ----------
    registry:
        Registry collaborator that owns the Silver writes.
    owner:
        Repository owner.
    name:
        Repository name.
    enabled:
        Desired ingestion state.

    Returns
    -------
    bool
        Whether the stored state changed.

    Raises
    ------
    RepositoryNotFoundError
        If no repository has that owner and name.
    StorageUnavailableError
        If the registry database cannot be written.

    """
    try:
        if enabled:
            return await registry.enable_ingestion(owner, name)
        return await registry.disable_ingestion(owner, name)
    except RegistryRepositoryNotFoundError as exc:
        raise RepositoryNotFoundError(owner, name) from exc
    except SQLAlchemyError as exc:
        raise StorageUnavailableError(STORAGE_MESSAGE) from exc


def _sync_error(estate_key: str, exc: RegistrySyncError) -> Exception:
    """Map a registry sync failure using its original cause when present.

    The registry wraps low-level SQLAlchemy failures instead of exposing them,
    so the original cause is the only place that distinguishes a uniqueness
    clash from an outage. Anything else falls back to the reason the registry
    reported.
    """
    match exc.__cause__:
        case IntegrityError():
            return EstateConflictError(CONFLICT_MESSAGE)
        case OperationalError() | InterfaceError():
            return StorageUnavailableError(STORAGE_MESSAGE)
    if exc.reason == ESTATE_NOT_FOUND_REASON:
        return EstateNotFoundError(estate_key)
    return RegistrySyncFailedError(str(exc))
