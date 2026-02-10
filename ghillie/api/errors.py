"""Domain exceptions and Falcon error handlers for the API layer.

This module defines domain-specific exceptions raised by API resources
and the corresponding Falcon error handler functions that translate them
into appropriate HTTP responses.

Usage
-----
Register error handlers on the Falcon app::

    from ghillie.api.errors import (
        RepositoryNotFoundError,
        handle_repository_not_found,
        handle_value_error,
    )

    app.add_error_handler(RepositoryNotFoundError, handle_repository_not_found)
    app.add_error_handler(ValueError, handle_value_error)

"""

from __future__ import annotations

import typing as typ

import falcon

if typ.TYPE_CHECKING:
    from falcon.asgi import Request, Response

__all__ = [
    "RepositoryNotFoundError",
    "handle_repository_not_found",
    "handle_value_error",
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


async def handle_repository_not_found(
    _req: Request,
    resp: Response,
    ex: RepositoryNotFoundError,
    _params: dict[str, typ.Any],
) -> None:
    """Map ``RepositoryNotFoundError`` to HTTP 404."""
    resp.status = falcon.HTTP_404
    resp.media = {
        "title": "Repository not found",
        "description": str(ex),
    }


async def handle_value_error(
    _req: Request,
    resp: Response,
    ex: ValueError,
    _params: dict[str, typ.Any],
) -> None:
    """Map ``ValueError`` to HTTP 400."""
    resp.status = falcon.HTTP_400
    resp.media = {
        "title": "Bad request",
        "description": str(ex),
    }
