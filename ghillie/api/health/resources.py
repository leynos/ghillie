"""Health probe resources for Kubernetes liveness and readiness checks.

These resources are stateless and do not require database access or
session management. They are always registered regardless of whether
database dependencies are available.
"""

from __future__ import annotations

import typing as typ

import falcon

if typ.TYPE_CHECKING:
    from falcon.asgi import Request, Response

__all__ = ["HealthResource", "ReadyResource"]


class HealthResource:
    """Resource for the /health endpoint returning JSON ``{"status": "ok"}``."""

    async def on_get(self, _req: Request, resp: Response) -> None:
        """Handle GET /health requests."""
        resp.media = {"status": "ok"}
        resp.status = falcon.HTTP_200


class ReadyResource:
    """Resource for the /ready endpoint returning JSON ``{"status": "ready"}``."""

    async def on_get(self, _req: Request, resp: Response) -> None:
        """Handle GET /ready requests."""
        resp.media = {"status": "ready"}
        resp.status = falcon.HTTP_200
