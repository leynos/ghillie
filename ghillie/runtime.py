"""Ghillie runtime entrypoint for Kubernetes deployments.

This module provides the ASGI application factory for Kubernetes
deployments.  It delegates to :func:`ghillie.api.app.create_app` for
application construction while keeping the ``ghillie.runtime:create_app``
Granian entrypoint stable.

When ``GHILLIE_DATABASE_URL`` is set, the runtime builds estate-management
dependencies so the app includes the estate endpoints. Report routes are
added only when ``GHILLIE_STATUS_MODEL_BACKEND`` is also set. Otherwise it
starts in health-only mode.

Configuration is driven by environment variables:

- ``GHILLIE_HOST``: Bind address (default ``0.0.0.0``)
- ``GHILLIE_PORT``: Listen port (default ``8080``)
- ``GHILLIE_LOG_LEVEL``: Log level (default ``INFO``)
- ``GHILLIE_DATABASE_URL``: Database connection URL (optional; enables
  estate endpoints when set)
- ``GHILLIE_STATUS_MODEL_BACKEND``: Status backend (optional; adds report
  routes when set)
- ``GHILLIE_API_TOKEN``: Bearer token guarding the API (optional; setting
  it enables authentication)
- ``GHILLIE_DB_BOOTSTRAP``: ``create-all`` creates missing tables at
  start-up (optional; any other value stops start-up)

Run the service directly with ``python -m ghillie.runtime``.
"""

from __future__ import annotations

import os
import typing as typ

from ghillie.api.health.resources import HealthResource, ReadyResource

if typ.TYPE_CHECKING:
    import falcon.asgi
from ghillie.logging import (
    configure_logging,
    get_logger,
    log_error,
    log_info,
    log_warning,
)

__all__ = ["HealthResource", "ReadyResource", "create_app", "main"]

logger = get_logger(__name__)

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
            raise ValueError(msg)  # noqa: TRY301 - unify conversion and range errors
    except ValueError as exc:
        # Use error() not exception() - validation failures need no traceback
        log_error(
            logger,
            "Invalid GHILLIE_PORT value: %r (must be %d-%d): %s",
            port_str,
            _MIN_PORT,
            _MAX_PORT,
            exc,
        )
        raise SystemExit(1) from exc
    return port


_BOOTSTRAP_CREATE_ALL = "create-all"


def _read_bootstrap_setting() -> str | None:
    """Return the raw ``GHILLIE_DB_BOOTSTRAP`` value, treating blank as unset.

    Raises
    ------
    SystemExit
        If the value is neither blank nor ``create-all``. An unknown mode is
        an operator error: starting with a half-configured schema is worse
        than refusing to start.

    """
    raw = os.environ.get("GHILLIE_DB_BOOTSTRAP")
    if raw is None or not raw.strip():
        return None
    if raw != _BOOTSTRAP_CREATE_ALL:
        log_error(
            logger,
            "Invalid GHILLIE_DB_BOOTSTRAP value: %r (expected %r or unset)",
            raw,
            _BOOTSTRAP_CREATE_ALL,
        )
        raise SystemExit(1)
    return raw


def create_app() -> falcon.asgi.App:
    """Create and configure the Falcon ASGI application.

    When ``GHILLIE_DATABASE_URL`` is set, builds the estate service so the
    app includes the estate endpoints. Report routes are added only when
    ``GHILLIE_STATUS_MODEL_BACKEND`` is also set. Otherwise only ``/health``
    and ``/ready`` are available.

    Returns
    -------
    falcon.asgi.App
        Configured Falcon ASGI application.

    """
    from ghillie.api.app import AppDependencies
    from ghillie.api.app import create_app as _create_api_app

    bootstrap = _read_bootstrap_setting()
    # Secrets supplied by files or shell helpers often carry a trailing
    # newline; the request parser strips the supplied credential, so the
    # configured value must be stripped too or a valid token never matches.
    api_token = (os.environ.get("GHILLIE_API_TOKEN") or "").strip() or None
    database_url = os.environ.get("GHILLIE_DATABASE_URL")

    if database_url is None:
        log_info(
            logger,
            "Starting API in health-only mode (set GHILLIE_DATABASE_URL to "
            "enable estate endpoints)",
        )
        return _create_api_app(AppDependencies(api_token=api_token))

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ghillie.api.factory import build_estate_service, build_reporting_service

    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    estate_service = build_estate_service(session_factory)

    has_status_backend = bool(os.environ.get("GHILLIE_STATUS_MODEL_BACKEND"))
    reporting_service = (
        build_reporting_service(session_factory) if has_status_backend else None
    )

    log_info(
        logger,
        "Starting API with estate endpoints (reports=%s, auth=%s, bootstrap=%s)",
        has_status_backend,
        api_token is not None,
        bootstrap is not None,
    )

    deps = AppDependencies(
        session_factory=session_factory,
        reporting_service=reporting_service,
        estate_service=estate_service,
        api_token=api_token,
        bootstrap_engine=engine if bootstrap is not None else None,
    )
    return _create_api_app(deps)


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

    # Configure logging - validate log level and warn on invalid values
    normalized_level, invalid_level = configure_logging(log_level_str)
    if invalid_level:
        log_warning(
            logger,
            "Invalid GHILLIE_LOG_LEVEL %r, falling back to %s",
            log_level_str,
            normalized_level,
        )

    log_info(
        logger,
        "Starting Ghillie runtime on %s:%d (log_level=%s)",
        host,
        port,
        normalized_level,
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
