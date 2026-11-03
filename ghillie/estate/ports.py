"""Driving port for estate management.

Adapters depend on this protocol rather than on the concrete service, so the
HTTP and CLI layers see only estate-owned types and errors.
"""

import typing as typ

if typ.TYPE_CHECKING:
    from ghillie.estate.models import (
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
    catalogue failures into :mod:`ghillie.estate.errors`.
    """

    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]:
        """Return a page of estates ordered by key."""
        ...

    async def import_catalogue(  # noqa: PLR0913 - mirrors the documented import request contract.
        self,
        estate_key: str,
        *,
        catalogue_yaml: str,
        commit_sha: str,
        estate_name: str | None,
        dry_run: bool,
    ) -> CatalogueImportSummary:
        """Import one catalogue document for an estate."""
        ...

    async def sync_registry(
        self, estate_key: str, *, dry_run: bool
    ) -> RegistrySyncSummary:
        """Project an estate's catalogue repositories into the registry."""
        ...

    async def list_repositories(
        self, estate_key: str, query: RepositoryQuery
    ) -> RepositoryPage:
        """Return a page of an estate's registered repositories."""
        ...

    async def set_ingestion(
        self, owner: str, name: str, *, enabled: bool
    ) -> IngestionToggleOutcome:
        """Set one repository's ingestion flag."""
        ...
