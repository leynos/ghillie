"""Persistence boundary for the estate-management service.

This is the only estate module that knows SQLAlchemy or the shape of a registry
failure. The service calls these functions instead of the catalogue query module
and the registry service directly, so every storage failure is classified here,
once, and leaves as an error :mod:`ghillie.estate.ports` already documents.
Hecate classifies the module as ``outbound_adapter``: the application service
may depend on it, and it depends only on the port and the modules that actually
reach a store.

Each public function states its store call and the translator that classifies a
failure, so the translation policy sits beside the call it applies to instead of
being repeated in every ``except`` clause. The translators are pure: they map
the failures they recognise and return ``None`` for anything else, which the
wrapper re-raises unchanged.
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
    import collections.abc as cabc

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

type FailureTranslator = cabc.Callable[[Exception], Exception | None]
"""Map a recognised store failure to an estate error, or return ``None``.

A translator that returns ``None`` has decided the failure is not one it owns;
the wrapper re-raises the original so an unexpected defect is never disguised
as a storage outcome.
"""


async def _translate[ResultT](
    operation: cabc.Coroutine[object, object, ResultT],
    translator: FailureTranslator,
) -> ResultT:
    """Await one store call, letting ``translator`` classify a failure.

    Parameters
    ----------
    operation:
        Coroutine for the store call. ``async def`` calls do not run until they
        are awaited, so creating it cannot skip the translation below.
    translator:
        Classification for a failure this operation can raise.

    Returns
    -------
    ResultT
        Whatever the store call returned.

    """
    try:
        return await operation
    except Exception as exc:
        translated = translator(exc)
        if translated is None:
            raise
        raise translated from exc


def _catalogue_failure(exc: Exception) -> Exception | None:
    """Classify a failed catalogue read as an outage, or pass it through."""
    if isinstance(exc, SQLAlchemyError):
        return StorageUnavailableError(STORAGE_MESSAGE)
    return None


def _import_failure(exc: Exception) -> Exception | None:
    """Classify a failed catalogue import as a conflict or an outage."""
    match exc:
        case IntegrityError():
            return EstateConflictError(CONFLICT_MESSAGE)
        case SQLAlchemyError():
            return StorageUnavailableError(STORAGE_MESSAGE)
    return None


def _sync_failure(estate_key: str) -> FailureTranslator:
    """Build the translator for one estate's registry sync."""

    def translate(exc: Exception) -> Exception | None:
        """Classify one registry sync failure for the estate it belongs to."""
        match exc:
            case RegistrySyncError():
                return _sync_error(estate_key, exc)
            case IntegrityError():
                return EstateConflictError(CONFLICT_MESSAGE)
            case SQLAlchemyError():
                return RegistrySyncFailedError(SYNC_FAILED_MESSAGE)
        return None

    return translate


def _ingestion_failure(owner: str, name: str) -> FailureTranslator:
    """Build the translator for one repository's ingestion toggle."""

    def translate(exc: Exception) -> Exception | None:
        """Classify one ingestion-toggle failure for the repository it names."""
        match exc:
            case RegistryRepositoryNotFoundError():
                return RepositoryNotFoundError(owner, name)
            case SQLAlchemyError():
                return StorageUnavailableError(STORAGE_MESSAGE)
        return None

    return translate


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
    return await _translate(
        queries.list_estates(session_factory, limit=limit, offset=offset),
        _catalogue_failure,
    )


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
    return await _translate(
        queries.get_estate_by_key(session_factory, estate_key),
        _catalogue_failure,
    )


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
    return await _translate(
        importer.import_catalogue(catalogue, commit_sha=commit_sha, dry_run=dry_run),
        _import_failure,
    )


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
    return await _translate(
        registry.sync_from_catalogue(estate_key, dry_run=dry_run),
        _sync_failure(estate_key),
    )


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
    return await _translate(
        registry.list_repositories(
            estate_id,
            ingestion_enabled=query.ingestion_enabled,
            limit=query.limit,
            offset=query.offset,
        ),
        _catalogue_failure,
    )


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
    toggle = (
        registry.enable_ingestion(owner, name)
        if enabled
        else registry.disable_ingestion(owner, name)
    )
    return await _translate(toggle, _ingestion_failure(owner, name))


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
