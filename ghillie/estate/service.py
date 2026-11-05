"""Application service coordinating catalogue import and registry sync.

The service owns the units of work behind estate management. It parses
untrusted YAML off the event loop, serializes import and sync per estate, and
translates catalogue, registry, and SQLAlchemy failures into the estate error
vocabulary so adapters never depend on an underlying package.
"""

import asyncio
import dataclasses
import time
import typing as typ
import weakref

from sqlalchemy.exc import (
    IntegrityError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)

from ghillie.catalogue.importer import CatalogueImporter, CatalogueImportResult
from ghillie.catalogue.loader import parse_catalogue_text
from ghillie.catalogue.queries import EstateRow, get_estate_by_key, list_estates
from ghillie.catalogue.validation import CatalogueValidationError
from ghillie.estate.errors import (
    CatalogueRejectedError,
    EstateConflictError,
    EstateNotFoundError,
    InvalidPaginationError,
    Issue,
    RegistrySyncFailedError,
    RepositoryNotFoundError,
    StorageUnavailableError,
)
from ghillie.estate.models import (
    MAX_PAGE_LIMIT,
    MAX_PAGE_OFFSET,
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
    validate_estate_key_reference,
    validate_new_estate_key,
)
from ghillie.logging import get_logger, log_info
from ghillie.registry.errors import ESTATE_NOT_FOUND_REASON, RegistrySyncError
from ghillie.registry.errors import (
    RepositoryNotFoundError as RegistryRepositoryNotFoundError,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.catalogue.models import Catalogue
    from ghillie.registry.models import SyncResult
    from ghillie.registry.service import RepositoryRegistryService

logger = get_logger(__name__)


class EstateManagementService:
    """Coordinate catalogue imports, registry syncs, listings, and toggles.

    Parameters
    ----------
    session_factory:
        Factory for async catalogue sessions.
    registry:
        Registry collaborator that projects catalogue repositories into Silver.

    Notes
    -----
    Imports and syncs for one estate are serialized by an in-process lock, so
    two concurrent requests cannot interleave their catalogue writes.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        registry: RepositoryRegistryService,
    ) -> None:
        """Store the session factory and registry collaborator."""
        self._session_factory = session_factory
        self._registry = registry
        # A weak map keeps per-estate serialization without retaining a lock
        # for every key a client has ever mentioned. A coroutine inside
        # ``async with`` holds the only strong reference, so an idle lock is
        # collected at once.
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]:
        """Return a page of estates ordered by key.

        Parameters
        ----------
        page:
            Requested limit and offset.

        Returns
        -------
        Page[EstateSummary]
            The requested page and its continuation metadata.

        Raises
        ------
        InvalidPaginationError
            If ``page.limit`` or ``page.offset`` is outside its allowed range.
        StorageUnavailableError
            If the catalogue database cannot be read.

        """
        _validate_page(page.limit, page.offset)
        try:
            rows = await list_estates(
                self._session_factory,
                limit=page.limit + 1,
                offset=page.offset,
            )
        except SQLAlchemyError as exc:
            raise StorageUnavailableError(_STORAGE_MESSAGE) from exc

        has_more = len(rows) > page.limit
        items = tuple(_estate_summary(row) for row in rows[: page.limit])
        return Page(
            items=items,
            limit=page.limit,
            offset=page.offset,
            has_more=has_more,
            next_offset=_next_offset(page.limit, page.offset, has_more=has_more),
        )

    async def import_catalogue(
        self,
        estate_key: str,
        request: CatalogueImportRequest,
    ) -> CatalogueImportSummary:
        """Import one catalogue document for an estate.

        Parameters
        ----------
        estate_key:
            Key of the estate to import into. A new estate is created when the
            key does not exist.
        request:
            Catalogue document and the metadata that accompanies it.

        Returns
        -------
        CatalogueImportSummary
            Counts and skip state for the import.

        Raises
        ------
        InvalidEstateKeyError
            If ``estate_key`` is empty or too long, or if it names a new
            estate and does not match the creation pattern.
        CatalogueRejectedError
            If the YAML is malformed or fails schema validation.
        EstateConflictError
            If the import conflicts with an existing record.
        StorageUnavailableError
            If the catalogue database cannot be written.

        """
        validate_estate_key_reference(estate_key)
        catalogue = await _parse_catalogue(request.catalogue_yaml)

        started = time.perf_counter()
        async with self._lock_for(estate_key):
            result = await self._run_import(estate_key, catalogue, request)

        summary = _import_summary(estate_key, request, result)
        _log_mutation(
            _MutationLog(
                operation="estate.import",
                estate_key=estate_key,
                commit_sha=request.commit_sha,
                dry_run=request.dry_run,
                started=started,
            ),
            outcome="skipped" if result.skipped else "succeeded",
            details=_import_details(summary),
        )
        return summary

    async def _run_import(
        self,
        estate_key: str,
        catalogue: Catalogue,
        request: CatalogueImportRequest,
    ) -> CatalogueImportResult:
        """Run the importer under the estate lock, translating its failures."""
        stored = await self._get_estate_row(estate_key)
        if stored is None:
            # D16: only a *new* estate is held to the strict creation pattern;
            # keys created earlier through Python must stay reachable through
            # the API.
            validate_new_estate_key(estate_key)
        resolved_name = (
            request.estate_name
            if request.estate_name is not None
            else (stored.name if stored is not None else None)
        )
        importer = CatalogueImporter(
            self._session_factory,
            estate_key=estate_key,
            estate_name=resolved_name,
        )
        try:
            result = await importer.import_catalogue(
                catalogue,
                commit_sha=request.commit_sha,
                dry_run=request.dry_run,
            )
        except CatalogueValidationError as exc:
            raise _catalogue_rejected(exc) from exc
        except IntegrityError as exc:
            raise EstateConflictError(_CONFLICT_MESSAGE) from exc
        except SQLAlchemyError as exc:
            raise StorageUnavailableError(_STORAGE_MESSAGE) from exc
        return result

    async def sync_registry(
        self, estate_key: str, *, dry_run: bool
    ) -> RegistrySyncSummary:
        """Project an estate's catalogue repositories into the registry.

        Parameters
        ----------
        estate_key:
            Key of the estate whose repositories should be synchronized.
        dry_run:
            When true, report the counts without persisting them.

        Returns
        -------
        RegistrySyncSummary
            Counts, conflicts, and repositories left disabled by the sync.

        Raises
        ------
        InvalidEstateKeyError
            If ``estate_key`` is empty or over the length limit.
        EstateNotFoundError
            If no estate has that key.
        EstateConflictError
            If the sync conflicts with an existing record.
        RegistrySyncFailedError
            If the registry reports a failure that is not storage-related.
        StorageUnavailableError
            If the catalogue or registry database cannot be reached.

        """
        validate_estate_key_reference(estate_key)

        started = time.perf_counter()
        async with self._lock_for(estate_key):
            result = await self._run_sync(estate_key, dry_run=dry_run)

        summary = _sync_summary(estate_key, result, dry_run=dry_run)
        _log_mutation(
            _MutationLog(
                operation="estate.registry-sync",
                estate_key=estate_key,
                commit_sha=None,
                dry_run=dry_run,
                started=started,
            ),
            outcome="succeeded",
            details=_sync_details(summary),
        )
        return summary

    async def _run_sync(self, estate_key: str, *, dry_run: bool) -> SyncResult:
        """Run the registry projection under the estate lock."""
        await self._require_estate(estate_key)
        try:
            result = await self._registry.sync_from_catalogue(
                estate_key, dry_run=dry_run
            )
        except RegistrySyncError as exc:
            raise _sync_error(estate_key, exc) from exc
        except IntegrityError as exc:
            raise EstateConflictError(_CONFLICT_MESSAGE) from exc
        except SQLAlchemyError as exc:
            raise RegistrySyncFailedError(_SYNC_FAILED_MESSAGE) from exc
        return result

    async def list_repositories(
        self, estate_key: str, query: RepositoryQuery
    ) -> RepositoryPage:
        """Return a page of an estate's registered repositories.

        Parameters
        ----------
        estate_key:
            Key of the estate whose repositories should be listed.
        query:
            Ingestion filter and requested limit and offset.

        Returns
        -------
        RepositoryPage
            The requested page and its continuation metadata.

        Raises
        ------
        InvalidEstateKeyError
            If ``estate_key`` is empty or over the length limit.
        InvalidPaginationError
            If ``query.limit`` or ``query.offset`` is outside its allowed range.
        EstateNotFoundError
            If no estate has that key.
        StorageUnavailableError
            If the registry database cannot be read.

        """
        validate_estate_key_reference(estate_key)
        _validate_page(query.limit, query.offset)

        estate = await self._require_estate(estate_key)
        try:
            # The registry owns the Silver session factory. Querying Silver
            # through the catalogue factory would read the wrong database when
            # the stores are deployed separately.
            repositories = await self._registry.list_repositories(
                estate.id,
                ingestion_enabled=query.ingestion_enabled,
                limit=query.limit + 1,
                offset=query.offset,
            )
        except SQLAlchemyError as exc:
            raise StorageUnavailableError(_STORAGE_MESSAGE) from exc

        has_more = len(repositories) > query.limit
        items = tuple(repositories[: query.limit])
        return RepositoryPage(
            estate_key=estate_key,
            items=items,
            limit=query.limit,
            offset=query.offset,
            has_more=has_more,
            next_offset=_next_offset(query.limit, query.offset, has_more=has_more),
        )

    async def set_ingestion(
        self, owner: str, name: str, *, enabled: bool
    ) -> IngestionToggleOutcome:
        """Set one repository's ingestion flag.

        Parameters
        ----------
        owner:
            Repository owner.
        name:
            Repository name.
        enabled:
            Desired ingestion state.

        Returns
        -------
        IngestionToggleOutcome
            The resulting state and whether the call changed it.

        Raises
        ------
        RepositoryNotFoundError
            If no repository has that owner and name.
        StorageUnavailableError
            If the registry database cannot be written.

        """
        started = time.perf_counter()
        try:
            changed = await self._toggle(owner, name, enabled=enabled)
        except RegistryRepositoryNotFoundError as exc:
            raise RepositoryNotFoundError(owner, name) from exc
        except SQLAlchemyError as exc:
            raise StorageUnavailableError(_STORAGE_MESSAGE) from exc

        previous = not enabled if changed else enabled
        log_info(
            logger,
            "estate.set-ingestion owner=%r name=%r enabled=%s "
            "previous=%s changed=%s duration_ms=%.1f outcome=succeeded",
            owner,
            name,
            enabled,
            previous,
            changed,
            _elapsed_ms(started),
        )
        return IngestionToggleOutcome(
            owner=owner,
            name=name,
            ingestion_enabled=enabled,
            changed=changed,
        )

    async def _toggle(self, owner: str, name: str, *, enabled: bool) -> bool:
        """Delegate the toggle so ``set_ingestion`` stays within complexity."""
        if enabled:
            return await self._registry.enable_ingestion(owner, name)
        return await self._registry.disable_ingestion(owner, name)

    async def _get_estate_row(self, estate_key: str) -> EstateRow | None:
        """Read one estate, translating storage failures."""
        try:
            return await get_estate_by_key(self._session_factory, estate_key)
        except SQLAlchemyError as exc:
            raise StorageUnavailableError(_STORAGE_MESSAGE) from exc

    async def _require_estate(self, estate_key: str) -> EstateRow:
        """Return an estate row or raise :class:`EstateNotFoundError`."""
        row = await self._get_estate_row(estate_key)
        if row is None:
            raise EstateNotFoundError(estate_key)
        return row

    def _lock_for(self, estate_key: str) -> asyncio.Lock:
        """Return the per-estate lock, creating it on first use."""
        lock = self._locks.get(estate_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[estate_key] = lock
        return lock


_STORAGE_MESSAGE = "storage is unavailable"
_CONFLICT_MESSAGE = "the write conflicts with an existing record"
_SYNC_FAILED_MESSAGE = "the registry sync failed"


def _estate_summary(row: EstateRow) -> EstateSummary:
    """Convert a catalogue row into the port's estate summary."""
    return EstateSummary(
        key=row.key,
        name=row.name,
        description=row.description,
        last_import_commit_sha=row.last_import_commit_sha,
        last_imported_at=row.last_imported_at,
    )


def _count_summary(created: int, updated: int, deleted: int) -> CountSummary:
    """Pack three record counts into the shared count summary."""
    return CountSummary(created=created, updated=updated, deleted=deleted)


async def _parse_catalogue(catalogue_yaml: str) -> Catalogue:
    """Parse untrusted YAML off the event loop, translating its failures."""
    try:
        catalogue = await asyncio.to_thread(parse_catalogue_text, catalogue_yaml)
    except CatalogueValidationError as exc:
        raise _catalogue_rejected(exc) from exc
    return catalogue


def _import_summary(
    estate_key: str,
    request: CatalogueImportRequest,
    result: CatalogueImportResult,
) -> CatalogueImportSummary:
    """Build the port summary from the importer's reconciliation result."""
    return CatalogueImportSummary(
        estate_key=estate_key,
        commit_sha=request.commit_sha,
        state="succeeded",
        dry_run=request.dry_run,
        skipped=result.skipped,
        skipped_reason="commit_already_imported" if result.skipped else None,
        registry_sync_required=not result.skipped and not request.dry_run,
        projects=_count_summary(
            result.projects_created,
            result.projects_updated,
            result.projects_deleted,
        ),
        components=_count_summary(
            result.components_created,
            result.components_updated,
            result.components_deleted,
        ),
        repositories=_count_summary(
            result.repositories_created,
            result.repositories_updated,
            result.repositories_deleted,
        ),
        edges=_count_summary(
            result.edges_created,
            result.edges_updated,
            result.edges_deleted,
        ),
    )


def _import_details(summary: CatalogueImportSummary) -> str:
    """Render the per-record counts for the structured import log line."""
    return (
        f"projects={summary.projects.created}/"
        f"{summary.projects.updated}/{summary.projects.deleted} "
        f"components={summary.components.created}/"
        f"{summary.components.updated}/{summary.components.deleted} "
        f"repositories={summary.repositories.created}/"
        f"{summary.repositories.updated}/"
        f"{summary.repositories.deleted}"
    )


def _sync_summary(
    estate_key: str,
    result: SyncResult,
    *,
    dry_run: bool,
) -> RegistrySyncSummary:
    """Build the port summary from the registry's sync result."""
    return RegistrySyncSummary(
        estate_key=estate_key,
        state="succeeded",
        dry_run=dry_run,
        repositories_created=result.repositories_created,
        repositories_updated=result.repositories_updated,
        repositories_deactivated=result.repositories_deactivated,
        repositories_conflicted=tuple(result.repositories_conflicted),
        repositories_left_disabled=tuple(result.repositories_left_disabled),
        repositories_left_disabled_count=result.repositories_left_disabled_count,
    )


def _sync_details(summary: RegistrySyncSummary) -> str:
    """Render the per-repository counts for the structured sync log line."""
    return (
        f"created={summary.repositories_created} "
        f"updated={summary.repositories_updated} "
        f"deactivated={summary.repositories_deactivated} "
        f"conflicted={len(summary.repositories_conflicted)} "
        f"left_disabled={summary.repositories_left_disabled_count}"
    )


def _catalogue_rejected(exc: CatalogueValidationError) -> CatalogueRejectedError:
    """Translate catalogue validation messages into port issues."""
    issues = tuple(
        Issue(code="catalogue_schema", message=message) for message in exc.issues
    )
    return CatalogueRejectedError(issues)


def _sync_error(estate_key: str, exc: RegistrySyncError) -> Exception:
    """Map a registry sync failure using its original cause when present."""
    # The registry wraps low-level SQLAlchemy failures instead of exposing
    # them, so the original cause is the only place that distinguishes a
    # uniqueness clash from an outage. Anything else falls back to the reason
    # the registry reported.
    match exc.__cause__:
        case IntegrityError():
            return EstateConflictError(_CONFLICT_MESSAGE)
        case OperationalError() | InterfaceError():
            return StorageUnavailableError(_STORAGE_MESSAGE)
    if exc.reason == ESTATE_NOT_FOUND_REASON:
        return EstateNotFoundError(estate_key)
    return RegistrySyncFailedError(str(exc))


def _validate_page(limit: int, offset: int) -> None:
    """Reject a page request outside the documented bounds."""
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        message = f"must be between 1 and {MAX_PAGE_LIMIT}"
        raise InvalidPaginationError("limit", message)
    if not 0 <= offset <= MAX_PAGE_OFFSET:
        message = f"must be between 0 and {MAX_PAGE_OFFSET}"
        raise InvalidPaginationError("offset", message)


def _next_offset(limit: int, offset: int, *, has_more: bool) -> int | None:
    """Return the following page's offset, or ``None`` on the last page."""
    return offset + limit if has_more else None


def _elapsed_ms(started: float) -> float:
    """Return the milliseconds elapsed since *started*."""
    return (time.perf_counter() - started) * 1000


@dataclasses.dataclass(frozen=True, slots=True)
class _MutationLog:
    """Request-scoped fields shared by every structured mutation line (D21)."""

    operation: str
    estate_key: str
    commit_sha: str | None
    dry_run: bool
    started: float


def _log_mutation(mutation: _MutationLog, *, outcome: str, details: str) -> None:
    """Write the one structured mutation line required by D21.

    ``estate_key`` and ``commit_sha`` come from the request, so they are
    rendered with ``%r``: a newline or other control character must appear as
    an escape rather than split the record into a forged second line.
    """
    log_info(
        logger,
        "%s estate_key=%r commit_sha=%r dry_run=%s %s duration_ms=%.1f outcome=%s",
        mutation.operation,
        mutation.estate_key,
        mutation.commit_sha or "-",
        mutation.dry_run,
        details,
        _elapsed_ms(mutation.started),
        outcome,
    )
