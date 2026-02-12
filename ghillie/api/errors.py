"""Domain exceptions and Falcon error handlers for the API layer.

This module defines domain-specific exceptions raised by API resources
and the corresponding Falcon error handler functions that translate them
into appropriate HTTP responses.

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

import falcon

if typ.TYPE_CHECKING:
    from falcon.asgi import Request, Response

__all__ = [
    "InvalidInputError",
    "RepositoryNotFoundError",
    "handle_invalid_input",
    "handle_repository_not_found",
]


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


async def handle_repository_not_found(
    _req: Request,
    resp: Response,
    ex: RepositoryNotFoundError,
    _params: dict[str, typ.Any],
) -> None:
    """Map ``RepositoryNotFoundError`` to an HTTP 404 JSON response.

    Parameters
    ----------
    _req
        Falcon request (unused).
    resp
        Falcon response whose status and media are set.
    ex
        The domain exception containing owner/name details.
    _params
        URI template parameters (unused).

    """
    resp.status = falcon.HTTP_404
    resp.media = {
        "title": "Repository not found",
        "description": str(ex),
    }


async def handle_invalid_input(
    _req: Request,
    resp: Response,
    ex: InvalidInputError,
    _params: dict[str, typ.Any],
) -> None:
    """Map ``InvalidInputError`` to an HTTP 400 JSON response.

    Parameters
    ----------
    _req
        Falcon request (unused).
    resp
        Falcon response whose status and media are set.
    ex
        The validation exception containing reason and optional field.
    _params
        URI template parameters (unused).

    """
    resp.status = falcon.HTTP_400
    media: dict[str, str] = {
        "title": "Invalid input",
        "description": ex.reason,
    }
    if ex.field is not None:
        media["field"] = ex.field
    resp.media = media
