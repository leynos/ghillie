"""Factories that assemble the services used by the HTTP API.

``build_estate_service(session_factory)`` builds an
``EstateManagementService`` for the estate routes. It passes the supplied
session factory as both registry database arguments, so catalogue and
registry work share the one configured database, and it reads no environment
configuration. :mod:`ghillie.runtime` builds it and passes the result to
``AppDependencies``, from which :mod:`ghillie.api.app` registers the estate
routes; without that dependency those routes are absent.

``build_reporting_service(session_factory)`` builds a fully configured
``ReportingService`` from the same kind of session factory plus the current
environment. This mirrors the Dramatiq actor's ``_build_service()`` pattern
but accepts a session factory directly rather than a database URL string.

Usage
-----
Build a service for the API layer::

    from ghillie.api.factory import build_reporting_service

    service = build_reporting_service(session_factory)

"""

from __future__ import annotations

import typing as typ

from ghillie.estate.service import EstateManagementService
from ghillie.evidence import EvidenceBundleService
from ghillie.registry.service import RepositoryRegistryService
from ghillie.reporting.config import ReportingConfig
from ghillie.reporting.observability import ReportingEventLogger
from ghillie.reporting.service import ReportingService, ReportingServiceDependencies
from ghillie.status.factory import create_status_model

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.reporting.sink import ReportSink

__all__ = ["build_estate_service", "build_reporting_service"]


def build_estate_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> EstateManagementService:
    """Build an ``EstateManagementService`` over one database.

    Parameters
    ----------
    session_factory
        Async session factory for the catalogue and Silver tables.

    Returns
    -------
    EstateManagementService
        A service wired to a registry over the same database.

    """
    registry = RepositoryRegistryService(session_factory, session_factory)
    return EstateManagementService(session_factory, registry=registry)


def build_reporting_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> ReportingService:
    """Build a ``ReportingService`` from environment configuration.

    Creates the evidence service, status model, reporting config, and
    optional filesystem sink from the current environment, then assembles
    a fully configured ``ReportingService``.

    Parameters
    ----------
    session_factory
        Async session factory for database access.

    Returns
    -------
    ReportingService
        Configured service ready for report generation.

    """
    evidence_service = EvidenceBundleService(session_factory)
    status_model = create_status_model()
    config = ReportingConfig.from_env()

    report_sink: ReportSink | None = None
    if config.report_sink_path is not None:
        from ghillie.reporting.filesystem_sink import FilesystemReportSink

        report_sink = FilesystemReportSink(config.report_sink_path)

    dependencies = ReportingServiceDependencies(
        session_factory=session_factory,
        evidence_service=evidence_service,
        status_model=status_model,
    )
    return ReportingService(
        dependencies,
        config=config,
        report_sink=report_sink,
        event_logger=ReportingEventLogger(),
    )
