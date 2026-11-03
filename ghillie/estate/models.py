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
    """One estate and its most recent catalogue import."""

    key: str
    name: str
    description: str | None
    last_import_commit_sha: str | None
    last_imported_at: dt.datetime | None


@dataclasses.dataclass(frozen=True, slots=True)
class CountSummary:
    """Created, updated, and deleted counts for one record family."""

    created: int
    updated: int
    deleted: int


@dataclasses.dataclass(frozen=True, slots=True)
class CatalogueImportSummary:
    """Result of importing one catalogue document for an estate."""

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
    """Result of projecting one estate's catalogue into the registry."""

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
    """Validated pagination input."""

    limit: int = DEFAULT_PAGE_LIMIT
    offset: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class Page[T]:
    """A page of items plus the metadata needed to walk the next page."""

    items: tuple[T, ...]
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None


@dataclasses.dataclass(frozen=True, slots=True)
class RepositoryQuery:
    """Filtering and pagination for an estate's repository listing."""

    ingestion_enabled: bool | None = None
    limit: int = DEFAULT_PAGE_LIMIT
    offset: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class RepositoryPage:
    """A page of an estate's registered repositories."""

    estate_key: str
    items: tuple[RepositoryInfo, ...]
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None


@dataclasses.dataclass(frozen=True, slots=True)
class IngestionToggleOutcome:
    """Result of setting one repository's ingestion flag."""

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
