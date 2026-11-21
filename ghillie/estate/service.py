"""Application service coordinating catalogue import and registry sync.

The service owns the units of work behind estate management. It validates a
request, serializes import and sync per estate, and orchestrates the importer
and registry. Storage failures are classified at the persistence boundary in
:mod:`ghillie.estate.persistence`, catalogue validation in
:mod:`ghillie.estate.translation`, and the D21 records come from
:mod:`ghillie.estate.observability` through the injected
:class:`~ghillie.estate.collaborators.EstateCollaborators`. The service itself
therefore contains only validation, locking, orchestration, and the decision of
which outcome applies.
"""

from __future__ import annotations

import asyncio
import dataclasses
import typing as typ
import weakref

from ghillie.catalogue.validation import CatalogueValidationError
from ghillie.estate import persistence, translation
from ghillie.estate.collaborators import (
    CatalogueParser,
    EstateCollaborators,
    ImporterFactory,
)
from ghillie.estate.errors import (
    EstateNotFoundError,
    InvalidPaginationError,
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
from ghillie.estate.observability import (
    MutationOutcome,
    MutationRecorder,
    failure_details,
    import_details,
    sync_details,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.catalogue.importer import CatalogueImportResult
    from ghillie.catalogue.models import Catalogue
    from ghillie.catalogue.queries import EstateRow
    from ghillie.registry.models import SyncResult
    from ghillie.registry.service import RepositoryRegistryService


class EstateManagementService:
    """Coordinate catalogue imports, registry syncs, listings, and toggles.

    Parameters
    ----------
    session_factory:
        Factory for async catalogue sessions.
    registry:
        Registry collaborator that projects catalogue repositories into Silver.
    collaborators:
        Importer factory, catalogue parser, and D21 recorder. ``None`` builds
        the production defaults; a test substitutes one value so it can parse
        without a database, supply an importer double, or pin the clock.

    Notes
    -----
    Imports and syncs for one estate are serialized by an in-process lock, so
    two concurrent requests cannot interleave their catalogue writes. The lock
    table belongs to this instance: calls that reach separate instances, worker
    processes, or replicas share no lock (D17), so the application builds one
    instance in a single replica.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        registry: RepositoryRegistryService,
        collaborators: EstateCollaborators | None = None,
    ) -> None:
        """Store the session factory, registry, and collaborators."""
        self._session_factory = session_factory
        self._registry = registry
        resolved = collaborators if collaborators is not None else EstateCollaborators()
        # Store each seam beside the service's own state rather than keeping
        # the bundle: every call site then names the collaborator it uses.
        self._importer_factory: ImporterFactory = resolved.importer_factory
        self._parse_text: CatalogueParser = resolved.parse_catalogue
        self._recorder: MutationRecorder = resolved.recorder
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
        rows = await persistence.list_estates(
            self._session_factory,
            limit=page.limit + 1,
            offset=page.offset,
        )

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
        mutation = self._recorder.begin_mutation(
            operation="estate.import",
            estate_key=estate_key,
            commit_sha=request.commit_sha,
            dry_run=request.dry_run,
        )
        try:
            validate_estate_key_reference(estate_key)
            catalogue = await self._parse_catalogue(request.catalogue_yaml)
            async with self._lock_for(estate_key):
                result = await self._run_import(estate_key, catalogue, request)
        except asyncio.CancelledError as exc:
            # D21: cancellation derives from ``BaseException``, so the clause
            # below cannot see it. It is still a terminal outcome, and it must
            # keep propagating so the caller's task unwinds.
            self._recorder.record_mutation(
                mutation,
                outcome=MutationOutcome.CANCELLED,
                details=failure_details(exc),
            )
            raise
        except Exception as exc:
            # D21: a rejected or failed attempt is still a mutation attempt, and
            # an operator needs its outcome and duration to tell a client error
            # apart from a storage outage.
            self._recorder.record_mutation(
                mutation,
                outcome=MutationOutcome.FAILED,
                details=failure_details(exc),
            )
            raise

        summary = _import_summary(estate_key, request, result)
        self._recorder.record_mutation(
            mutation,
            outcome=(
                MutationOutcome.SKIPPED if result.skipped else MutationOutcome.SUCCEEDED
            ),
            details=import_details(summary),
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
        importer = self._importer_factory(
            self._session_factory,
            estate_key=estate_key,
            estate_name=resolved_name,
        )
        try:
            result = await persistence.import_catalogue(
                importer,
                catalogue,
                commit_sha=request.commit_sha,
                dry_run=request.dry_run,
            )
        except CatalogueValidationError as exc:
            raise translation.catalogue_rejected(exc) from exc
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
        mutation = self._recorder.begin_mutation(
            operation="estate.registry-sync",
            estate_key=estate_key,
            commit_sha=None,
            dry_run=dry_run,
        )
        try:
            validate_estate_key_reference(estate_key)
            async with self._lock_for(estate_key):
                result = await self._run_sync(estate_key, dry_run=dry_run)
        except asyncio.CancelledError as exc:
            # D21: as for the import, cancellation is a terminal outcome the
            # ``except Exception`` clause below would miss.
            self._recorder.record_mutation(
                mutation,
                outcome=MutationOutcome.CANCELLED,
                details=failure_details(exc),
            )
            raise
        except Exception as exc:
            self._recorder.record_mutation(
                mutation,
                outcome=MutationOutcome.FAILED,
                details=failure_details(exc),
            )
            raise

        summary = _sync_summary(estate_key, result, dry_run=dry_run)
        self._recorder.record_mutation(
            mutation,
            outcome=MutationOutcome.SUCCEEDED,
            details=sync_details(summary),
        )
        return summary

    async def _run_sync(self, estate_key: str, *, dry_run: bool) -> SyncResult:
        """Run the registry projection under the estate lock."""
        await self._require_estate(estate_key)
        return await persistence.sync_registry(
            self._registry, estate_key, dry_run=dry_run
        )

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
        # The registry owns the Silver session factory. Querying Silver through
        # the catalogue factory would read the wrong database when the stores
        # are deployed separately. Read one row past the page so the caller can
        # tell whether a further page exists.
        over_fetch = dataclasses.replace(query, limit=query.limit + 1)
        repositories = await persistence.list_repositories(
            self._registry, estate.id, over_fetch
        )

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
        toggle = self._recorder.begin_toggle(owner=owner, name=name, enabled=enabled)
        try:
            changed = await persistence.set_ingestion(
                self._registry, owner, name, enabled=enabled
            )
        except asyncio.CancelledError as exc:
            # D21: cancellation is a terminal outcome the ``except Exception``
            # clause below would miss, and it must keep propagating.
            self._recorder.record_toggle(
                toggle,
                outcome=MutationOutcome.CANCELLED,
                details=failure_details(exc),
            )
            raise
        except Exception as exc:
            # D21: a direct service caller has no HTTP catch-all, so any failure
            # must still leave one terminal record. The persistence adapter has
            # already translated storage and registry failures, so the record
            # names the error the caller will see.
            self._recorder.record_toggle(
                toggle,
                outcome=MutationOutcome.FAILED,
                details=failure_details(exc),
            )
            raise

        previous = not enabled if changed else enabled
        self._recorder.record_toggle(
            toggle,
            outcome=MutationOutcome.SUCCEEDED,
            details=f"previous={previous} changed={changed}",
        )
        return IngestionToggleOutcome(
            owner=owner,
            name=name,
            ingestion_enabled=enabled,
            changed=changed,
        )

    async def _parse_catalogue(self, catalogue_yaml: str) -> Catalogue:
        """Parse untrusted YAML off the event loop, translating its failures."""
        try:
            catalogue = await asyncio.to_thread(self._parse_text, catalogue_yaml)
        except CatalogueValidationError as exc:
            raise translation.catalogue_rejected(exc) from exc
        return catalogue

    async def _get_estate_row(self, estate_key: str) -> EstateRow | None:
        """Read one estate; the persistence adapter translates storage failures."""
        return await persistence.get_estate_by_key(self._session_factory, estate_key)

    async def _require_estate(self, estate_key: str) -> EstateRow:
        """Return an estate row or raise :class:`EstateNotFoundError`."""
        row = await self._get_estate_row(estate_key)
        if row is None:
            raise EstateNotFoundError(estate_key)
        return row

    def _lock_for(self, estate_key: str) -> asyncio.Lock:
        """Return the per-estate lock, creating it on first use.

        The lock table belongs to this instance only, so it serializes calls
        that reach the same service object. Separate instances, worker
        processes, and replicas share no lock and may run operations for one
        estate concurrently (D17), which is why the runtime builds a single
        instance.
        """
        lock = self._locks.get(estate_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[estate_key] = lock
        return lock


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
