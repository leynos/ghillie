"""Pure data types shared by the estate-management port and its adapters.

The module imports only the standard library and other ``domain_ports``
modules so Hecate can keep it free of persistence and transport concerns.
"""

import dataclasses
import re
import typing as typ

from ghillie.estate.errors import InvalidEstateKeyError

if typ.TYPE_CHECKING:
    import datetime as dt

    from ghillie.registry.models import RepositoryInfo

MAX_ESTATE_KEY_LENGTH = 64
MAX_PAGE_LIMIT = 500
MAX_PAGE_OFFSET = 2**31 - 1
"""Largest offset the API accepts.

SQLite raises a bare ``OverflowError`` when a caller binds a value beyond its
signed 64-bit range, and PostgreSQL rejects an out-of-range ``OFFSET`` as a
storage error. A signed 32-bit ceiling keeps both backends inside their native
integer range while remaining far beyond any real estate listing.
"""

DEFAULT_PAGE_LIMIT = 50
MAX_REQUEST_BODY_BYTES = 1024 * 1024
"""Largest catalogue-import or toggle body the HTTP adapter accepts.

The catalogue document is the only unbounded field a client supplies, so one
megabyte comfortably covers a large estate's YAML while bounding what a single
request can make the process buffer.
"""

NEW_ESTATE_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
"""Pattern a *new* estate key must match.

Other endpoints accept any key of one to :data:`MAX_ESTATE_KEY_LENGTH`
characters so that keys created earlier through Python stay reachable.
"""

_NEW_ESTATE_KEY_RE = re.compile(NEW_ESTATE_KEY_PATTERN)


@dataclasses.dataclass(frozen=True, slots=True)
class EstateSummary:
    """One estate and its most recent catalogue import.

    Attributes
    ----------
    key:
        Operator-facing estate key.
    name:
        Display name of the estate.
    description:
        Optional operator description, or ``None``.
    last_import_commit_sha:
        Commit of the latest catalogue import, or ``None`` if never imported.
    last_imported_at:
        Time of the latest catalogue import, or ``None`` if never imported.

    """

    key: str
    name: str
    description: str | None
    last_import_commit_sha: str | None
    last_imported_at: dt.datetime | None


@dataclasses.dataclass(frozen=True, slots=True)
class CountSummary:
    """Created, updated, and deleted counts for one record family.

    Attributes
    ----------
    created:
        Rows inserted by the operation.
    updated:
        Existing rows changed by the operation.
    deleted:
        Rows removed by the operation.

    """

    created: int
    updated: int
    deleted: int


@dataclasses.dataclass(frozen=True, slots=True)
class CatalogueImportRequest:
    """Inputs for importing one catalogue revision into an estate.

    Grouping the document and its metadata keeps the port signature small and
    lets adapters pass the same value through without re-listing each field.

    Attributes
    ----------
    catalogue_yaml:
        Catalogue document as YAML text.
    commit_sha:
        Commit the document was read from.
    estate_name:
        Display name to store. ``None`` keeps an existing name and names a new
        estate after its key.
    dry_run:
        When true, report the counts without persisting them.

    """

    catalogue_yaml: str
    commit_sha: str
    estate_name: str | None = None
    dry_run: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class CatalogueImportSummary:
    """Result of importing one catalogue document for an estate.

    Attributes
    ----------
    estate_key:
        Key of the estate that was imported.
    commit_sha:
        Commit the catalogue document was read from.
    state:
        Terminal state of the import operation.
    dry_run:
        Whether the import was reported without being persisted.
    skipped:
        Whether the commit had already been imported.
    skipped_reason:
        Why the import was skipped, or ``None`` when it ran.
    registry_sync_required:
        Whether a registry sync should follow this import.
    projects:
        Project record counts.
    components:
        Component record counts.
    repositories:
        Repository record counts.
    edges:
        Component edge counts.

    """

    estate_key: str
    commit_sha: str
    state: str
    dry_run: bool
    skipped: bool
    skipped_reason: str | None
    registry_sync_required: bool
    projects: CountSummary
    components: CountSummary
    repositories: CountSummary
    edges: CountSummary


@dataclasses.dataclass(frozen=True, slots=True)
class RegistrySyncSummary:
    """Result of projecting one estate's catalogue into the registry.

    Attributes
    ----------
    estate_key:
        Key of the estate that was synchronized.
    state:
        Terminal state of the sync operation.
    dry_run:
        Whether the sync was reported without being persisted.
    repositories_created:
        Repositories added to the registry.
    repositories_updated:
        Existing repositories whose metadata changed.
    repositories_deactivated:
        Repositories disabled because they left the catalogue.
    repositories_conflicted:
        Slugs that could not be projected because of an ownership conflict.
    repositories_left_disabled:
        Preview of repositories that remain disabled after the sync.
    repositories_left_disabled_count:
        Total number of repositories left disabled.

    """

    estate_key: str
    state: str
    dry_run: bool
    repositories_created: int
    repositories_updated: int
    repositories_deactivated: int
    repositories_conflicted: tuple[str, ...]
    repositories_left_disabled: tuple[str, ...]
    repositories_left_disabled_count: int


@dataclasses.dataclass(frozen=True, slots=True)
class PageRequest:
    """Validated pagination input.

    Attributes
    ----------
    limit:
        Maximum number of items to return.
    offset:
        Number of ordered items to skip.

    """

    limit: int = DEFAULT_PAGE_LIMIT
    offset: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class Page[T]:
    """A page of items plus the metadata needed to walk the next page.

    Attributes
    ----------
    items:
        Items in this page's order.
    limit:
        Maximum number of items requested.
    offset:
        Number of ordered items skipped to reach this page.
    has_more:
        Whether at least one further item exists after this page.
    next_offset:
        Offset that returns the next page, or ``None`` on the last page.

    """

    items: tuple[T, ...]
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None


@dataclasses.dataclass(frozen=True, slots=True)
class RepositoryQuery:
    """Filtering and pagination for an estate's repository listing.

    Attributes
    ----------
    ingestion_enabled:
        Optional ingestion-state filter; ``None`` lists both states.
    limit:
        Maximum number of repositories to return.
    offset:
        Number of ordered repositories to skip.

    """

    ingestion_enabled: bool | None = None
    limit: int = DEFAULT_PAGE_LIMIT
    offset: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class RepositoryPage:
    """A page of an estate's registered repositories.

    Attributes
    ----------
    estate_key:
        Key of the estate these repositories belong to.
    items:
        Repositories in this page's order.
    limit:
        Maximum number of repositories requested.
    offset:
        Number of ordered repositories skipped to reach this page.
    has_more:
        Whether at least one further repository exists after this page.
    next_offset:
        Offset that returns the next page, or ``None`` on the last page.

    """

    estate_key: str
    items: tuple[RepositoryInfo, ...]
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None


@dataclasses.dataclass(frozen=True, slots=True)
class IngestionToggleOutcome:
    """Result of setting one repository's ingestion flag.

    Attributes
    ----------
    owner:
        GitHub repository owner.
    name:
        GitHub repository name.
    ingestion_enabled:
        Ingestion state after the call.
    changed:
        Whether the call actually changed the stored state.

    """

    owner: str
    name: str
    ingestion_enabled: bool
    changed: bool


def validate_new_estate_key(estate_key: str) -> str:
    """Return ``estate_key`` when it is valid for creating an estate.

    Parameters
    ----------
    estate_key:
        Candidate key supplied by an operator.

    Returns
    -------
    str
        The unchanged key.

    Raises
    ------
    InvalidEstateKeyError
        If the key does not match :data:`NEW_ESTATE_KEY_PATTERN`.

    """
    if not _NEW_ESTATE_KEY_RE.fullmatch(estate_key):
        message = f"must match {NEW_ESTATE_KEY_PATTERN}"
        raise InvalidEstateKeyError(estate_key, message)
    return estate_key


def validate_estate_key_reference(estate_key: str) -> str:
    """Return ``estate_key`` when it can reference an existing estate.

    Parameters
    ----------
    estate_key:
        Candidate key supplied by an operator.

    Returns
    -------
    str
        The unchanged key.

    Raises
    ------
    InvalidEstateKeyError
        If the key is empty or longer than :data:`MAX_ESTATE_KEY_LENGTH`.

    """
    if not estate_key or len(estate_key) > MAX_ESTATE_KEY_LENGTH:
        message = f"must contain between 1 and {MAX_ESTATE_KEY_LENGTH} characters"
        raise InvalidEstateKeyError(estate_key, message)
    return estate_key
