"""Translate underlying failures into the estate error vocabulary.

Adapters depend on :mod:`ghillie.estate.errors` alone, so every catalogue,
registry, and SQLAlchemy failure has to be translated before it leaves the
service. These functions are pure: they decide *which* estate error a failure
becomes and never log, so the service keeps ownership of the D21 record that
accompanies each outcome.
"""

from __future__ import annotations

import typing as typ

from sqlalchemy.exc import (
    IntegrityError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)

from ghillie.estate.errors import (
    CatalogueRejectedError,
    EstateConflictError,
    EstateNotFoundError,
    Issue,
    RegistrySyncFailedError,
    RepositoryNotFoundError,
    StorageUnavailableError,
)
from ghillie.registry.errors import ESTATE_NOT_FOUND_REASON, RegistrySyncError
from ghillie.registry.errors import (
    RepositoryNotFoundError as RegistryRepositoryNotFoundError,
)

if typ.TYPE_CHECKING:
    from ghillie.catalogue.validation import CatalogueValidationError

STORAGE_MESSAGE = "storage is unavailable"
CONFLICT_MESSAGE = "the write conflicts with an existing record"
SYNC_FAILED_MESSAGE = "the registry sync failed"


def catalogue_rejected(exc: CatalogueValidationError) -> CatalogueRejectedError:
    """Translate catalogue validation messages into port issues.

    Parameters
    ----------
    exc:
        The validation failure raised while parsing the uploaded document.

    Returns
    -------
    CatalogueRejectedError
        One ``catalogue_schema`` issue per validation message.

    """
    issues = tuple(
        Issue(code="catalogue_schema", message=message) for message in exc.issues
    )
    return CatalogueRejectedError(issues)


def sync_error(estate_key: str, exc: RegistrySyncError) -> Exception:
    """Map a registry sync failure using its original cause when present.

    Parameters
    ----------
    estate_key:
        Key the sync was asked to project.
    exc:
        The failure the registry reported.

    Returns
    -------
    Exception
        The estate error the port should raise instead.

    """
    # The registry wraps low-level SQLAlchemy failures instead of exposing
    # them, so the original cause is the only place that distinguishes a
    # uniqueness clash from an outage. Anything else falls back to the reason
    # the registry reported.
    match exc.__cause__:
        case IntegrityError():
            return EstateConflictError(CONFLICT_MESSAGE)
        case OperationalError() | InterfaceError():
            return StorageUnavailableError(STORAGE_MESSAGE)
    if exc.reason == ESTATE_NOT_FOUND_REASON:
        return EstateNotFoundError(estate_key)
    return RegistrySyncFailedError(str(exc))


def toggle_failure(
    exc: Exception,
    *,
    owner: str,
    name: str,
) -> Exception | None:
    """Return the estate error an ingestion-toggle failure becomes.

    Parameters
    ----------
    exc:
        The failure raised while changing the flag.
    owner:
        Repository owner named in the request.
    name:
        Repository name named in the request.

    Returns
    -------
    Exception or None
        The translated error, or ``None`` when the failure has no translation.
        ``None`` tells the caller to re-raise the original error unchanged, so
        an unexpected failure stays visible rather than being disguised as a
        contract error.

    """
    match exc:
        case RegistryRepositoryNotFoundError():
            return RepositoryNotFoundError(owner, name)
        case SQLAlchemyError():
            return StorageUnavailableError(STORAGE_MESSAGE)
    return None
