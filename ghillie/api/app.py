"""Application factory for the Ghillie Falcon ASGI application.

This module provides ``create_app()`` which builds and configures the
Falcon ASGI application with health endpoints and, when database
dependencies are available, domain endpoints for report generation.

Usage
-----
Create a health-only app (no database)::

    app = create_app()

Create a full app with domain endpoints::

    from ghillie.api.app import AppDependencies, create_app

    deps = AppDependencies(
        session_factory=session_factory,
        reporting_service=reporting_service,
    )
    app = create_app(deps)

"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

import falcon.asgi

from ghillie.api.errors import (
    InvalidInputError,
    RepositoryNotFoundError,
    handle_invalid_input,
    handle_repository_not_found,
)
from ghillie.api.health.resources import HealthResource, ReadyResource

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.reporting.service import ReportingService

__all__ = ["AppDependencies", "create_app"]


@dc.dataclass(frozen=True, slots=True)
class AppDependencies:
    """Dependencies for the Falcon ASGI application.

    When ``session_factory`` and ``reporting_service`` are both provided,
    the application includes session middleware and domain endpoints.
    Otherwise only health endpoints are registered.

    Attributes
    ----------
    session_factory
        Async session factory for database access.
    reporting_service
        Reporting service for on-demand report generation.

    """

    session_factory: async_sessionmaker[AsyncSession] | None = None
    reporting_service: ReportingService | None = None


def _has_domain_deps(deps: AppDependencies | None) -> bool:
    """Return True when deps provide both session factory and service."""
    return (
        deps is not None
        and deps.session_factory is not None
        and deps.reporting_service is not None
    )


def create_app(
    dependencies: AppDependencies | None = None,
) -> falcon.asgi.App:
    """Create and configure the Falcon ASGI application.

    When *dependencies* provides a session factory and reporting service,
    the app includes ``SQLAlchemySessionManager`` middleware and the
    ``POST /reports/repositories/{owner}/{name}`` endpoint.  Otherwise
    only ``/health`` and ``/ready`` are registered.

    Parameters
    ----------
    dependencies
        Optional application dependencies.  When ``None``, only health
        endpoints are available.

    Returns
    -------
    falcon.asgi.App
        Configured Falcon ASGI application.

    """
    middleware: list[object] = []

    if _has_domain_deps(dependencies) and dependencies is not None:
        from ghillie.api.middleware import SQLAlchemySessionManager

        # _has_domain_deps guarantees non-None; cast to satisfy the
        # type checker without assert + noqa.
        sf = typ.cast("async_sessionmaker[AsyncSession]", dependencies.session_factory)
        middleware.append(SQLAlchemySessionManager(sf))

    app = falcon.asgi.App(middleware=middleware)  # type: ignore[no-matching-overload]  # Falcon stubs

    # Health endpoints are always available
    app.add_route("/health", HealthResource())
    app.add_route("/ready", ReadyResource())

    # Domain endpoints require database dependencies
    if _has_domain_deps(dependencies) and dependencies is not None:
        from ghillie.api.gold.resources import ReportResource

        sf = typ.cast("async_sessionmaker[AsyncSession]", dependencies.session_factory)
        rs = typ.cast("ReportingService", dependencies.reporting_service)
        app.add_route(
            "/reports/repositories/{owner}/{name}",
            ReportResource(session_factory=sf, reporting_service=rs),
        )

    # Error handlers
    app.add_error_handler(RepositoryNotFoundError, handle_repository_not_found)
    app.add_error_handler(InvalidInputError, handle_invalid_input)

    return app
