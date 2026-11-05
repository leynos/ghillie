"""Domain exceptions and Falcon error handlers for the API layer.

Every error response shares one envelope (D7): ``title``, ``description``,
a stable ``code``, and optionally ``field``, ``issues``, or ``max_bytes``.
Keeping the envelope uniform lets the CLI map a machine-readable ``code`` to
an actionable hint instead of parsing prose.

Usage
-----
Register error handlers on the Falcon app::

    from ghillie.api.errors import (
        InvalidInputError,
        RepositoryNotFoundError,
        handle_invalid_input,
        handle_repository_not_found,
    )

    app.add_error_handler(RepositoryNotFoundError, handle_repository_not_found)
    app.add_error_handler(InvalidInputError, handle_invalid_input)

"""

from __future__ import annotations

import typing as typ
from http import HTTPStatus

from ghillie.logging import get_logger, log_exception

if typ.TYPE_CHECKING:
    import falcon
    from falcon.asgi import Request, Response

    from ghillie.estate.errors import (
        CatalogueRejectedError,
        EstateConflictError,
        EstateNotFoundError,
        InvalidEstateKeyError,
        InvalidPaginationError,
        RegistrySyncFailedError,
        StorageUnavailableError,
    )
    from ghillie.estate.errors import (
        RepositoryNotFoundError as EstateRepositoryNotFoundError,
    )
    from ghillie.reporting.errors import ReportValidationError

__all__ = [
    "InvalidInputError",
    "PayloadTooLargeError",
    "RepositoryNotFoundError",
    "handle_catalogue_rejected",
    "handle_estate_conflict",
    "handle_estate_not_found",
    "handle_estate_repository_not_found",
    "handle_falcon_http_error",
    "handle_invalid_estate_key",
    "handle_invalid_input",
    "handle_invalid_pagination",
    "handle_payload_too_large",
    "handle_registry_sync_failed",
    "handle_report_validation_failed",
    "handle_repository_not_found",
    "handle_storage_unavailable",
    "handle_unexpected_error",
]

logger = get_logger(__name__)

# Falcon's own errors still pass through the envelope; this table gives them a
# stable code where the status has an obvious meaning. Unknown statuses fall
# back to ``http_<status>`` so a client can still branch on it.
_HTTP_ERROR_CODES = {
    HTTPStatus.BAD_REQUEST: "invalid_input",
    HTTPStatus.UNAUTHORIZED: "unauthorized",
    HTTPStatus.NOT_FOUND: "not_found",
    HTTPStatus.METHOD_NOT_ALLOWED: "method_not_allowed",
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE: "payload_too_large",
    HTTPStatus.UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    HTTPStatus.UNPROCESSABLE_ENTITY: "unprocessable_entity",
}


class RepositoryNotFoundError(Exception):
    """Raised when a repository is not found by owner/name slug.

    Attributes
    ----------
    owner
        GitHub repository owner.
    name
        GitHub repository name.

    """

    def __init__(self, owner: str, name: str) -> None:
        """Initialize with the repository owner and name.

        Parameters
        ----------
        owner
            GitHub repository owner.
        name
            GitHub repository name.

        """
        self.owner = owner
        self.name = name
        super().__init__(f"No repository matching '{owner}/{name}' exists.")


class InvalidInputError(Exception):
    """Raised for client validation errors that should map to HTTP 400.

    Use this instead of ``ValueError`` so that only *intentional*
    validation failures are surfaced to the caller, while genuine
    programmer mistakes still propagate as unhandled 500s.

    Attributes
    ----------
    reason
        Human-readable description of the validation failure.
    field
        Optional name of the input field that failed validation.

    """

    def __init__(self, reason: str, *, field: str | None = None) -> None:
        """Initialize with a validation reason and optional field name.

        Parameters
        ----------
        reason
            Human-readable description of the validation failure.
        field
            Optional name of the input field that failed validation.

        """
        self.reason = reason
        self.field = field
        message = f"{field}: {reason}" if field is not None else reason
        super().__init__(message)


class PayloadTooLargeError(Exception):
    """Raised when a request body exceeds ``MAX_REQUEST_BODY_BYTES``.

    Attributes
    ----------
    max_bytes
        Largest body the endpoint accepts, echoed so a client can trim the
        upload without guessing the limit.

    """

    def __init__(self, max_bytes: int) -> None:
        """Initialize with the accepted body size limit."""
        self.max_bytes = max_bytes
        super().__init__(f"Request body must not exceed {max_bytes} bytes.")


def _set_error(  # noqa: PLR0913 - the envelope's fields are all distinct.
    resp: Response,
    *,
    status: HTTPStatus | int,
    title: str,
    code: str,
    description: str,
    extra: dict[str, typ.Any] | None = None,
) -> None:
    """Set the shared error envelope on *resp*."""
    media: dict[str, typ.Any] = {
        "title": title,
        "description": description,
        "code": code,
    }
    if extra:
        media.update(extra)
    resp.status = status
    resp.media = media


async def handle_repository_not_found(
    _req: Request,
    resp: Response,
    ex: RepositoryNotFoundError,
    _params: dict[str, typ.Any],
) -> None:
    """Map ``RepositoryNotFoundError`` to an HTTP 404 JSON response."""
    _set_error(
        resp,
        status=HTTPStatus.NOT_FOUND,
        title="Repository not found",
        code="repository_not_found",
        description=str(ex),
    )


async def handle_invalid_input(
    _req: Request,
    resp: Response,
    ex: InvalidInputError,
    _params: dict[str, typ.Any],
) -> None:
    """Map ``InvalidInputError`` to an HTTP 400 JSON response."""
    extra = {"field": ex.field} if ex.field is not None else None
    _set_error(
        resp,
        status=HTTPStatus.BAD_REQUEST,
        title="Invalid input",
        code="invalid_input",
        description=ex.reason,
        extra=extra,
    )


async def handle_payload_too_large(
    _req: Request,
    resp: Response,
    ex: PayloadTooLargeError,
    _params: dict[str, typ.Any],
) -> None:
    """Map ``PayloadTooLargeError`` to an HTTP 413 JSON response.

    Parameters
    ----------
    _req:
        Request that carried the oversized body.
    resp:
        Response to populate with the error envelope.
    ex:
        Exception carrying the accepted body-size limit.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    _set_error(
        resp,
        status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        title="Payload too large",
        code="payload_too_large",
        description=str(ex),
        extra={"max_bytes": ex.max_bytes},
    )


async def handle_estate_not_found(
    _req: Request,
    resp: Response,
    ex: EstateNotFoundError,
    _params: dict[str, typ.Any],
) -> None:
    """Map an unknown estate to an HTTP 404 JSON response.

    Parameters
    ----------
    _req:
        Request that named the missing estate.
    resp:
        Response to populate with the error envelope.
    ex:
        Error carrying the estate key that was not found.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    _set_error(
        resp,
        status=HTTPStatus.NOT_FOUND,
        title="Estate not found",
        code="estate_not_found",
        description=str(ex),
    )


async def handle_estate_repository_not_found(
    _req: Request,
    resp: Response,
    ex: EstateRepositoryNotFoundError,
    _params: dict[str, typ.Any],
) -> None:
    """Map an unknown repository to an HTTP 404 JSON response.

    Parameters
    ----------
    _req:
        Request that named the missing repository.
    resp:
        Response to populate with the error envelope.
    ex:
        Error carrying the owner and name that were not found.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    _set_error(
        resp,
        status=HTTPStatus.NOT_FOUND,
        title="Repository not found",
        code="repository_not_found",
        description=str(ex),
    )


async def handle_invalid_estate_key(
    _req: Request,
    resp: Response,
    ex: InvalidEstateKeyError,
    _params: dict[str, typ.Any],
) -> None:
    """Map a rejected estate key to an HTTP 400 JSON response.

    Parameters
    ----------
    _req:
        Request that carried the rejected key.
    resp:
        Response to populate with the error envelope.
    ex:
        Error carrying the key and the rule it broke.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    _set_error(
        resp,
        status=HTTPStatus.BAD_REQUEST,
        title="Invalid input",
        code="invalid_input",
        description=ex.reason,
        extra={"field": "estate_key"},
    )


async def handle_invalid_pagination(
    _req: Request,
    resp: Response,
    ex: InvalidPaginationError,
    _params: dict[str, typ.Any],
) -> None:
    """Map an out-of-range page limit or offset to HTTP 400.

    Parameters
    ----------
    _req:
        Request that carried the invalid pagination.
    resp:
        Response to populate with the error envelope.
    ex:
        Error naming the invalid field and its allowed range.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    _set_error(
        resp,
        status=HTTPStatus.BAD_REQUEST,
        title="Invalid input",
        code="invalid_input",
        description=ex.reason,
        extra={"field": ex.field},
    )


async def handle_catalogue_rejected(
    _req: Request,
    resp: Response,
    ex: CatalogueRejectedError,
    _params: dict[str, typ.Any],
) -> None:
    """Map catalogue validation issues to an HTTP 422 JSON response.

    Parameters
    ----------
    _req:
        Request that uploaded the invalid catalogue.
    resp:
        Response to populate with the error envelope.
    ex:
        Error carrying the catalogue validation issues.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    _set_error(
        resp,
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        title="Catalogue invalid",
        code="catalogue_invalid",
        description="The catalogue document failed validation.",
        extra={
            "issues": [
                {"code": issue.code, "message": issue.message} for issue in ex.issues
            ]
        },
    )


async def handle_estate_conflict(
    _req: Request,
    resp: Response,
    ex: EstateConflictError,
    _params: dict[str, typ.Any],
) -> None:
    """Map a uniqueness conflict to an HTTP 409 JSON response.

    Parameters
    ----------
    _req:
        Request whose write conflicted with stored state.
    resp:
        Response to populate with the error envelope.
    ex:
        Error describing the conflict without driver detail.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    _set_error(
        resp,
        status=HTTPStatus.CONFLICT,
        title="Conflict",
        code="conflict",
        description=str(ex) or "The write conflicts with an existing record.",
    )


async def handle_storage_unavailable(
    _req: Request,
    resp: Response,
    ex: StorageUnavailableError,
    _params: dict[str, typ.Any],
) -> None:
    """Map an unreachable database to an HTTP 503 JSON response.

    Parameters
    ----------
    _req:
        Request that needed the unavailable database.
    resp:
        Response to populate with the error envelope.
    ex:
        Error describing the unavailable storage without driver detail. It is
        logged here because the chained driver exception is a server-side
        fault the operator must be able to diagnose.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    log_exception(logger, "Storage unavailable", ex)
    _set_error(
        resp,
        status=HTTPStatus.SERVICE_UNAVAILABLE,
        title="Storage unavailable",
        code="storage_unavailable",
        description=str(ex) or "Storage is unavailable.",
    )


async def handle_registry_sync_failed(
    _req: Request,
    resp: Response,
    ex: RegistrySyncFailedError,
    _params: dict[str, typ.Any],
) -> None:
    """Map an unexpected sync failure to an HTTP 500 JSON response.

    Parameters
    ----------
    _req:
        Request that triggered the failed sync.
    resp:
        Response to populate with the error envelope.
    ex:
        Sync failure, logged here because it is a server-side fault.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    log_exception(logger, "Registry sync failed", ex)
    _set_error(
        resp,
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        title="Registry sync failed",
        code="registry_sync_failed",
        description=str(ex) or "The registry sync failed.",
    )


async def handle_falcon_http_error(
    _req: Request,
    resp: Response,
    ex: falcon.HTTPError,
    _params: dict[str, typ.Any],
) -> None:
    """Render Falcon's own HTTP errors through the shared envelope.

    Parameters
    ----------
    _req:
        Request that triggered the HTTP error.
    resp:
        Response to populate with the error envelope.
    ex:
        Falcon error carrying the status, title, description, and headers.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    status_code = ex.status_code
    try:
        status = HTTPStatus(status_code)
    except ValueError:
        # Falcon allows a non-standard numeric status; render it as-is.
        status = status_code
    code = _HTTP_ERROR_CODES.get(status)
    if code is None:
        code = f"http_{status_code}"
    # Falcon attaches headers such as ``WWW-Authenticate`` to the error; the
    # envelope handler must copy them or a 401 would lose its challenge.
    if ex.headers:
        # ``set_headers`` accepts both mapping and iterable header forms, so a
        # list-form ``HTTPError`` keeps its headers instead of raising.
        resp.set_headers(ex.headers)
    _set_error(
        resp,
        status=status,
        title=ex.title,
        code=code,
        description=ex.description or ex.title,
    )


async def handle_report_validation_failed(
    _req: Request,
    resp: Response,
    ex: ReportValidationError,
    _params: dict[str, typ.Any],
) -> None:
    """Map ``ReportValidationError`` to an HTTP 422 JSON response.

    Parameters
    ----------
    _req:
        Request that generated the invalid report.
    resp:
        Response to populate with the validation envelope.
    ex:
        Error carrying the review identifier and validation issues.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    resp.status = HTTPStatus.UNPROCESSABLE_ENTITY
    resp.media = {
        "title": "Report validation failed",
        "description": "Generated report failed correctness checks after retries.",
        "code": "report_validation_failed",
        "review_id": ex.review_id,
        "issues": [
            {"code": issue.code, "message": issue.message} for issue in ex.issues
        ],
    }


async def handle_unexpected_error(
    _req: Request,
    resp: Response,
    ex: Exception,
    _params: dict[str, typ.Any],
) -> None:
    """Render an unhandled exception as the shared 500 envelope (D7).

    The details stay in the log; the response is deliberately generic so an
    internal failure never leaks implementation detail to a client.

    Parameters
    ----------
    _req:
        Request whose handling raised the exception.
    resp:
        Response to populate with the generic error envelope.
    ex:
        Unhandled exception, logged for operators but not returned.
    _params:
        Falcon's per-route error-handler parameters.

    Returns
    -------
    None

    """
    log_exception(logger, "Unhandled API error", ex)
    _set_error(
        resp,
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        title="Internal server error",
        code="internal_error",
        description="An unexpected error occurred.",
    )
