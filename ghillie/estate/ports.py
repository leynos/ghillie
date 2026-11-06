"""Driving port for estate management.

Adapters depend on this protocol rather than on the concrete service, so the
HTTP and CLI layers see only estate-owned types and errors.
"""

import typing as typ

# Importing the models at runtime keeps ``typing.get_type_hints`` working for
# adapters and documentation tools; names that live only under
# ``TYPE_CHECKING`` are unresolvable once PEP 649 evaluates the annotations.
from ghillie.estate.models import (  # noqa: TC001
    CatalogueImportRequest,
    CatalogueImportSummary,
    EstateSummary,
    IngestionToggleOutcome,
    Page,
    PageRequest,
    RegistrySyncSummary,
    RepositoryPage,
    RepositoryQuery,
)


class EstateManagement(typ.Protocol):
    """Operations an operator can perform on estates.

    Implementations own their units of work and translate persistence and
    catalogue failures into :mod:`ghillie.estate.errors`. Adapters therefore
    depend only on this protocol and that error vocabulary.

    Notes
    -----
    Every method may raise
    :class:`~ghillie.estate.errors.StorageUnavailableError` when the database
    cannot be reached. The remaining errors are documented per method.

    """

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
        ...

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
            If ``estate_key`` does not match the creation pattern.
        CatalogueRejectedError
            If the YAML is malformed or fails schema validation.
        EstateConflictError
            If the import conflicts with an existing record.
        StorageUnavailableError
            If the catalogue database cannot be written.

        """
        ...

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
        ...

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
        ...

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
        ...
