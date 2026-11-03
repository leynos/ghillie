"""Reusable doubles for the estate-management port.

Route-registration tests need the port registered but never call most of its
methods. Keeping one empty double here stops every new test module from
repeating the five-method signature, which must otherwise be updated in each
copy whenever the port changes.
"""

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

__all__ = ["EmptyEstateManagement"]


class EmptyEstateManagement:
    """Estate port double that returns an empty first page."""

    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]:
        """Return an empty page."""
        return Page(
            items=(),
            limit=page.limit,
            offset=page.offset,
            has_more=False,
            next_offset=None,
        )

    async def import_catalogue(  # noqa: PLR0913 - mirrors the port signature.
        self,
        estate_key: str,
        *,
        catalogue_yaml: str,
        commit_sha: str,
        estate_name: str | None,
        dry_run: bool,
    ) -> CatalogueImportSummary:
        """Raise because these tests never import a catalogue."""
        raise NotImplementedError

    async def sync_registry(
        self, estate_key: str, *, dry_run: bool
    ) -> RegistrySyncSummary:
        """Raise because these tests never synchronise the registry."""
        raise NotImplementedError

    async def list_repositories(
        self, estate_key: str, query: RepositoryQuery
    ) -> RepositoryPage:
        """Raise because these tests never list repositories."""
        raise NotImplementedError

    async def set_ingestion(
        self, owner: str, name: str, *, enabled: bool
    ) -> IngestionToggleOutcome:
        """Raise because these tests never toggle ingestion."""
        raise NotImplementedError
