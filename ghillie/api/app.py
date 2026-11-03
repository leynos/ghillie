"""Application factory for the Ghillie Falcon ASGI application.

This module provides ``create_app()`` which builds and configures the
Falcon ASGI application with health endpoints and, when the relevant
dependencies are available, estate-management and report-generation
endpoints.

Usage
-----
Create a health-only app (no database)::

    app = create_app()

Create a full app with domain endpoints::

    from ghillie.api.app import AppDependencies, create_app

    deps = AppDependencies(
        session_factory=session_factory,
        reporting_service=reporting_service,
        estate_service=estate_service,
    )
    app = create_app(deps)

"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

import falcon
import falcon.asgi

from ghillie.api.errors import (
    InvalidInputError,
    PayloadTooLargeError,
    RepositoryNotFoundError,
    handle_catalogue_rejected,
    handle_estate_conflict,
    handle_estate_not_found,
    handle_estate_repository_not_found,
    handle_falcon_http_error,
    handle_invalid_estate_key,
    handle_invalid_input,
    handle_invalid_pagination,
    handle_payload_too_large,
    handle_registry_sync_failed,
    handle_report_validation_failed,
    handle_repository_not_found,
    handle_storage_unavailable,
    handle_unexpected_error,
)
from ghillie.api.health.resources import HealthResource, ReadyResource
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

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from ghillie.estate.ports import EstateManagement
    from ghillie.reporting.service import ReportingService

__all__ = ["AppDependencies", "create_app"]


class AsyncMiddlewareProto(typ.Protocol):
    """Minimal Falcon ASGI middleware shape used by the app factory."""

    async def process_request(
        self,
        req: falcon.asgi.Request,
        resp: falcon.asgi.Response,
    ) -> None:
        """Handle an incoming ASGI request before routing."""
        ...

    async def process_response(
        self,
        req: falcon.asgi.Request,
        resp: falcon.asgi.Response,
        resource: object,
        req_succeeded: bool,  # noqa: FBT001 - Falcon ASGI middleware requires a positional bool here; FIXME: ghillie#60 revisit if Falcon exposes a public typed middleware contract.
    ) -> None:
        """Handle an outgoing ASGI response after routing."""
        ...


@dc.dataclass(frozen=True, slots=True)
class AppDependencies:
    """Dependencies for the Falcon ASGI application.

    Each route family is independent: estate routes appear whenever
    ``estate_service`` is supplied, while reporting routes additionally need
    ``session_factory`` and ``reporting_service``.

    Attributes
    ----------
    session_factory
        Async session factory for database access.
    reporting_service
        Reporting service for on-demand report generation.
    estate_service
        Estate-management port backing the estate endpoints.
    api_token
        Optional bearer token. When set, every route except the probes
        requires it.
    bootstrap_engine
        Engine whose schema is created at ASGI start-up when supplied.

    """

    session_factory: async_sessionmaker[AsyncSession] | None = None
    reporting_service: ReportingService | None = None
    estate_service: EstateManagement | None = None
    api_token: str | None = None
    bootstrap_engine: AsyncEngine | None = None


def _has_domain_deps(deps: AppDependencies | None) -> bool:
    """Return True when deps provide both session factory and service."""
    return (
        deps is not None
        and deps.session_factory is not None
        and deps.reporting_service is not None
    )


def _build_middleware(
    deps: AppDependencies | None,
) -> list[AsyncMiddlewareProto]:
    """Assemble the middleware stack in the order it must run.

    Authentication runs first so an unauthenticated request never opens a
    database session. The bootstrap middleware only implements the ASGI
    lifespan hooks, which is why it is appended last.
    """
    from ghillie.api.auth import BearerTokenMiddleware

    middleware: list[AsyncMiddlewareProto] = []
    if deps is not None and deps.api_token:
        middleware.append(BearerTokenMiddleware(deps.api_token))

    if _has_domain_deps(deps):
        from ghillie.api.middleware import SQLAlchemySessionManager

        deps_with_session = typ.cast("AppDependencies", deps)
        sf = typ.cast(
            "async_sessionmaker[AsyncSession]", deps_with_session.session_factory
        )
        middleware.append(
            typ.cast("AsyncMiddlewareProto", SQLAlchemySessionManager(sf))
        )

    if deps is not None and deps.bootstrap_engine is not None:
        from ghillie.storage_bootstrap import StorageBootstrapMiddleware

        # This component implements only the ASGI lifespan hooks, so it is
        # cast to the request/response protocol the list is typed with.
        middleware.append(
            typ.cast(
                "AsyncMiddlewareProto",
                StorageBootstrapMiddleware(deps.bootstrap_engine),
            )
        )

    return middleware


def _register_estate_routes(app: falcon.asgi.App, estates: EstateManagement) -> None:
    """Register every estate-management route on *app*."""
    from ghillie.api.estate.resources import (
        CatalogueImportResource,
        EstateCollectionResource,
        EstateRepositoryCollectionResource,
        RegistrySyncResource,
        RepositoryIngestionResource,
    )

    app.add_route("/estates", EstateCollectionResource(estates=estates))
    app.add_route(
        "/estates/{estate_key}/catalogue-import",
        CatalogueImportResource(estates=estates),
    )
    app.add_route(
        "/estates/{estate_key}/registry-sync",
        RegistrySyncResource(estates=estates),
    )
    app.add_route(
        "/estates/{estate_key}/repositories",
        EstateRepositoryCollectionResource(estates=estates),
    )
    app.add_route(
        "/repositories/{owner}/{name}/ingestion",
        RepositoryIngestionResource(estates=estates),
    )


def _register_error_handlers(app: falcon.asgi.App) -> None:
    """Install the shared error envelope for every failure type (D7)."""
    app.add_error_handler(RepositoryNotFoundError, handle_repository_not_found)
    app.add_error_handler(InvalidInputError, handle_invalid_input)
    app.add_error_handler(PayloadTooLargeError, handle_payload_too_large)
    app.add_error_handler(ReportValidationError, handle_report_validation_failed)
    app.add_error_handler(EstateNotFoundError, handle_estate_not_found)
    app.add_error_handler(
        EstateRepositoryNotFoundError, handle_estate_repository_not_found
    )
    app.add_error_handler(InvalidEstateKeyError, handle_invalid_estate_key)
    app.add_error_handler(InvalidPaginationError, handle_invalid_pagination)
    app.add_error_handler(CatalogueRejectedError, handle_catalogue_rejected)
    app.add_error_handler(EstateConflictError, handle_estate_conflict)
    app.add_error_handler(StorageUnavailableError, handle_storage_unavailable)
    app.add_error_handler(RegistrySyncFailedError, handle_registry_sync_failed)
    app.add_error_handler(falcon.HTTPError, handle_falcon_http_error)
    # Every failure reaching a client must use the envelope, including one no
    # domain handler anticipated.
    app.add_error_handler(Exception, handle_unexpected_error)


def create_app(
    dependencies: AppDependencies | None = None,
) -> falcon.asgi.App:
    """Create and configure the Falcon ASGI application.

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
    deps = dependencies
    app = falcon.asgi.App(middleware=_build_middleware(deps))

    # Health endpoints are always available
    app.add_route("/health", HealthResource())
    app.add_route("/ready", ReadyResource())

    # Domain endpoints require their own dependencies.
    if _has_domain_deps(deps):
        from ghillie.api.gold.resources import ReportResource

        deps_with_reporting = typ.cast("AppDependencies", deps)
        rs = typ.cast("ReportingService", deps_with_reporting.reporting_service)
        app.add_route(
            "/reports/repositories/{owner}/{name}",
            ReportResource(reporting_service=rs),
        )

    if deps is not None and deps.estate_service is not None:
        _register_estate_routes(app, deps.estate_service)

    _register_error_handlers(app)

    return app
