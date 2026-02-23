"""Health probe resources for Kubernetes liveness and readiness checks.

These resources are stateless and do not require database access or
session management. They are always registered regardless of whether
database dependencies are available.

Usage
-----
Register health endpoints on the Falcon app::

    from ghillie.api.health.resources import HealthResource, ReadyResource

    app.add_route("/health", HealthResource())
    app.add_route("/ready", ReadyResource())

"""

from __future__ import annotations

import typing as typ
from http import HTTPStatus

if typ.TYPE_CHECKING:
    from falcon.asgi import Request, Response

__all__ = ["HealthResource", "ReadyResource"]


class HealthResource:
    """Liveness probe resource returning ``{"status": "ok"}``.

    Always responds with HTTP 200 to indicate the process is alive.
    No parameters or request body are expected.

    """

    async def on_get(self, _req: Request, resp: Response) -> None:
        """Handle GET /health requests.

        Parameters
        ----------
        _req
            Falcon request (unused).
        resp
            Falcon response populated with liveness status.

        """
        resp.media = {"status": "ok"}
        resp.status = HTTPStatus.OK


class ReadyResource:
    """Readiness probe resource returning ``{"status": "ready"}``.

    Always responds with HTTP 200 to indicate the service can accept
    traffic.  No parameters or request body are expected.

    """

    async def on_get(self, _req: Request, resp: Response) -> None:
        """Handle GET /ready requests.

        Parameters
        ----------
        _req
            Falcon request (unused).
        resp
            Falcon response populated with readiness status.

        """
        resp.media = {"status": "ready"}
        resp.status = HTTPStatus.OK
