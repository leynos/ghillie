"""Ghillie runtime entrypoint for Kubernetes deployments.

This module provides the ASGI application and HTTP endpoints for Kubernetes
health probes. It exposes ``/health`` and ``/ready`` endpoints on the
configured port (default 8080).

Configuration is driven by environment variables:

- ``GHILLIE_HOST``: Bind address (default ``0.0.0.0``)
- ``GHILLIE_PORT``: Listen port (default ``8080``)
- ``GHILLIE_LOG_LEVEL``: Log level (default ``INFO``)

Run the service directly with ``python -m ghillie.runtime``.
"""

from __future__ import annotations

import logging
import os
import typing as typ

import falcon.asgi
import falcon.media

if typ.TYPE_CHECKING:
    from falcon.asgi import Request, Response

__all__ = ["HealthResource", "ReadyResource", "create_app", "main"]

logger = logging.getLogger(__name__)

# TCP port number range limits
_MIN_PORT = 1
_MAX_PORT = 65535


def _parse_port(port_str: str) -> int:
    """Parse and validate a port number string.

    Raises
    ------
    SystemExit
        If port_str is not a valid integer in range 1-65535.

    """
    try:
        port = int(port_str)
        if not (_MIN_PORT <= port <= _MAX_PORT):
            msg = f"port {port} outside valid range {_MIN_PORT}-{_MAX_PORT}"
            raise ValueError(msg)  # noqa: TRY301 - intentional re-raise for unified error handling
    except ValueError as exc:
        # Use error() not exception() - validation failures need no traceback
        logger.error(  # noqa: TRY400 - no traceback for config validation
            "Invalid GHILLIE_PORT value: %r (must be %d-%d): %s",
            port_str,
            _MIN_PORT,
            _MAX_PORT,
            exc,
        )
        raise SystemExit(1) from exc
    return port


class HealthResource:
    """Resource for the /health endpoint returning JSON ``{"status": "ok"}``."""

    async def on_get(self, req: Request, resp: Response) -> None:
        """Handle GET /health requests."""
        resp.media = {"status": "ok"}
        resp.status = falcon.HTTP_200


class ReadyResource:
    """Resource for the /ready endpoint returning JSON ``{"status": "ready"}``."""

    async def on_get(self, req: Request, resp: Response) -> None:
        """Handle GET /ready requests."""
        resp.media = {"status": "ready"}
        resp.status = falcon.HTTP_200


def create_app() -> falcon.asgi.App:
    """Create and configure the Falcon ASGI application with health endpoints."""
    app = falcon.asgi.App()
    app.add_route("/health", HealthResource())
    app.add_route("/ready", ReadyResource())
    return app


def main() -> None:
    """Start the Ghillie runtime server using Granian.

    Reads ``GHILLIE_HOST``, ``GHILLIE_PORT``, and ``GHILLIE_LOG_LEVEL`` from
    the environment and starts the ASGI server.
    """
    from granian import Granian
    from granian.constants import Interfaces

    host = os.environ.get("GHILLIE_HOST", "0.0.0.0")  # noqa: S104 - bind all interfaces for container
    port_str = os.environ.get("GHILLIE_PORT", "8080")
    port = _parse_port(port_str)
    log_level_str = os.environ.get("GHILLIE_LOG_LEVEL", "INFO")

    # Configure logging
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    logger.info(
        "Starting Ghillie runtime on %s:%d (log_level=%s)",
        host,
        port,
        log_level_str,
    )

    server = Granian(
        "ghillie.runtime:create_app",
        address=host,
        port=port,
        interface=Interfaces.ASGI,
        factory=True,
    )
    server.serve()


if __name__ == "__main__":
    main()
