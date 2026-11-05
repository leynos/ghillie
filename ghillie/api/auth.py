"""Optional bearer-token authentication middleware (D14).

The token is configured through ``GHILLIE_API_TOKEN``. When it is unset, every
route stays open so local development needs no ceremony. When it is set, every
route except the liveness and readiness probes requires an
``Authorization: Bearer <token>`` header. A blank token also counts as
unconfigured here, but the process launcher refuses that case before the app is
built, so a misconfigured deployment cannot open itself silently.

Health probes stay exempt because orchestrators cannot be expected to hold the
API token, and a failing probe would otherwise restart a healthy process.
"""

from __future__ import annotations

import hmac
import typing as typ

import falcon

from ghillie.logging import get_logger, log_warning

if typ.TYPE_CHECKING:
    from falcon.asgi import Request, Response

__all__ = ["BearerTokenMiddleware"]

logger = get_logger(__name__)

_UNAUTHENTICATED_PATHS = frozenset({"/health", "/ready"})
_MIN_RECOMMENDED_TOKEN_LENGTH = 16


def _bearer_token(authorization: str) -> str | None:
    """Return the credentials of a bearer header, or ``None`` if malformed."""
    scheme, separator, credentials = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    return credentials.strip() or None


class BearerTokenMiddleware:
    """Falcon ASGI middleware enforcing a configured bearer token.

    Parameters
    ----------
    token
        Expected token. Falsy values disable authentication entirely.

    """

    def __init__(self, token: str | None) -> None:
        """Store the expected token, warning when authentication is off."""
        self._token = token or None
        if self._token is None:
            log_warning(
                logger,
                "GHILLIE_API_TOKEN is not set; estate API authentication is disabled",
            )
        elif len(self._token) < _MIN_RECOMMENDED_TOKEN_LENGTH:
            log_warning(
                logger,
                "GHILLIE_API_TOKEN is shorter than %d characters; prefer a "
                "long random value",
                _MIN_RECOMMENDED_TOKEN_LENGTH,
            )

    async def process_request(self, req: Request, resp: Response) -> None:
        """Reject a request that does not carry the configured token.

        Parameters
        ----------
        req
            Incoming request; its path and ``Authorization`` header are read.
        resp
            Response object, unused on the success path.

        Raises
        ------
        falcon.HTTPUnauthorized
            When authentication is enabled and the header is missing or wrong.

        """
        if self._token is None or req.path in _UNAUTHENTICATED_PATHS:
            return
        supplied = _bearer_token(req.get_header("Authorization") or "")
        # Compare bytes: ``hmac.compare_digest`` raises TypeError for
        # non-ASCII strings, and an unauthenticated client can send a Latin-1
        # header value that Falcon decodes into one.
        if supplied is not None and hmac.compare_digest(
            supplied.encode("utf-8"), self._token.encode("utf-8")
        ):
            return
        # The challenge makes the 401 self-describing to a generic client and
        # matches the bearer scheme documented in the OpenAPI description.
        raise falcon.HTTPUnauthorized(
            title="Unauthorized",
            description="A valid bearer token is required.",
            challenges=("Bearer",),
        )

    async def process_response(
        self,
        req: Request,
        resp: Response,
        resource: object,
        req_succeeded: bool,  # noqa: FBT001 - Falcon middleware signature.
    ) -> None:
        """No-op response hook required by the middleware protocol.

        Parameters
        ----------
        req
            Outgoing request, unused.
        resp
            Outgoing response, unused.
        resource
            Routed resource, unused.
        req_succeeded
            Whether the request succeeded, unused.

        """
