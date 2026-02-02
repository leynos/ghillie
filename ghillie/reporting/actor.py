"""Dramatiq actors for scheduled report generation.

This module provides Dramatiq actors for asynchronous report generation,
following the pattern established in the catalogue importer.

Usage
-----
Queue a single repository report:

>>> generate_report_job.send(
...     database_url="postgresql+asyncpg://...",
...     repository_id="550e8400-e29b-41d4-a716-446655440000",
... )

Queue reports for all repositories in an estate:

>>> generate_reports_for_estate_job.send(
...     database_url="postgresql+asyncpg://...",
...     estate_id="estate-1",
... )

"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import typing as typ

import dramatiq
from dramatiq.brokers.stub import StubBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ghillie.evidence import EvidenceBundleService
from ghillie.reporting.config import ReportingConfig
from ghillie.reporting.service import ReportingService
from ghillie.silver.storage import Repository
from ghillie.status.factory import create_status_model

if typ.TYPE_CHECKING:
    from ghillie.gold.storage import Report
    from ghillie.status.protocol import StatusModel

SessionFactory = async_sessionmaker[AsyncSession]

# Module-level caches for reusing expensive resources across actor invocations
_ENGINE_CACHE: dict[str, AsyncEngine] = {}
_SERVICE_CACHE: dict[str, ReportingService] = {}


def _get_or_create_engine(database_url: str) -> AsyncEngine:
    """Get or create an async engine for the given database URL."""
    if database_url not in _ENGINE_CACHE:
        _ENGINE_CACHE[database_url] = create_async_engine(database_url, future=True)
    return _ENGINE_CACHE[database_url]


def _get_or_create_service(
    session_factory: SessionFactory,
    database_url: str,
) -> ReportingService:
    """Get or create a ReportingService with cached dependencies."""
    if database_url not in _SERVICE_CACHE:
        evidence_service = EvidenceBundleService(session_factory)
        status_model = create_status_model()
        config = ReportingConfig.from_env()
        _SERVICE_CACHE[database_url] = ReportingService(
            session_factory=session_factory,
            evidence_service=evidence_service,
            status_model=status_model,
            config=config,
        )
    return _SERVICE_CACHE[database_url]


async def _generate_report_async(
    session_factory: SessionFactory,
    repository_id: str,
    as_of: dt.datetime | None = None,
    *,
    status_model: StatusModel | None = None,
) -> Report | None:
    """Generate a report for a single repository (async implementation).

    Parameters
    ----------
    session_factory
        Async session factory for database access.
    repository_id
        The Silver layer repository ID.
    as_of
        Reference time for window computation; defaults to now.
    status_model
        Optional status model; uses factory if not provided.

    Returns
    -------
    Report | None
        The generated report, or None if no events in window.

    """
    evidence_service = EvidenceBundleService(session_factory)
    if status_model is None:
        status_model = create_status_model()
    config = ReportingConfig.from_env()
    service = ReportingService(
        session_factory=session_factory,
        evidence_service=evidence_service,
        status_model=status_model,
        config=config,
    )
    return await service.run_for_repository(repository_id, as_of=as_of)


async def _generate_reports_for_estate_async(
    session_factory: SessionFactory,
    estate_id: str,
    as_of: dt.datetime | None = None,
    *,
    status_model: StatusModel | None = None,
) -> list[Report | None]:
    """Generate reports for all active repositories in an estate.

    Parameters
    ----------
    session_factory
        Async session factory for database access.
    estate_id
        The estate ID to scope repository selection.
    as_of
        Reference time for window computation; defaults to now.
    status_model
        Optional status model; uses factory if not provided.

    Returns
    -------
    list[Report | None]
        List of generated reports; None entries for repositories with no events.

    """
    # Fetch active repositories in the estate
    async with session_factory() as session:
        repos = (
            await session.scalars(
                select(Repository).where(
                    Repository.estate_id == estate_id,
                    Repository.ingestion_enabled.is_(True),
                )
            )
        ).all()
        repo_ids = [repo.id for repo in repos]

    # Generate reports for each repository
    results: list[Report | None] = []
    for repo_id in repo_ids:
        report = await _generate_report_async(
            session_factory=session_factory,
            repository_id=repo_id,
            as_of=as_of,
            status_model=status_model,
        )
        results.append(report)

    return results


# Ensure Dramatiq broker is configured (following catalogue/importer.py pattern)
try:  # pragma: no cover - exercised in tests and CLI usage
    _current_broker = dramatiq.get_broker()
except ModuleNotFoundError:
    _current_broker = None

if _current_broker is None:
    allow_stub = os.environ.get("GHILLIE_ALLOW_STUB_BROKER", "")
    running_tests = "pytest" in sys.modules or any(
        key in os.environ
        for key in ["PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS"]
    )
    if allow_stub.lower() in {"1", "true", "yes"} or running_tests:
        dramatiq.set_broker(StubBroker())
    else:  # pragma: no cover - guard for prod misconfigurations
        message = (
            "No Dramatiq broker configured. Set GHILLIE_ALLOW_STUB_BROKER=1 for "
            "local/test runs or configure a real broker."
        )
        raise RuntimeError(message)


@dramatiq.actor
def generate_report_job(
    database_url: str,
    repository_id: str,
    *,
    as_of_iso: str | None = None,
) -> str | None:
    """Dramatiq actor for generating a single repository report.

    Parameters
    ----------
    database_url
        SQLAlchemy URL for the database.
    repository_id
        The Silver layer repository ID.
    as_of_iso
        Optional ISO format timestamp for window computation.

    Returns
    -------
    str | None
        The report ID if generated, or None if no events in window.

    """
    as_of = dt.datetime.fromisoformat(as_of_iso) if as_of_iso else None

    engine = _get_or_create_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run() -> str | None:
        service = _get_or_create_service(session_factory, database_url)
        report = await service.run_for_repository(repository_id, as_of=as_of)
        return report.id if report else None

    return asyncio.run(run())


@dramatiq.actor
def generate_reports_for_estate_job(
    database_url: str,
    estate_id: str,
    *,
    as_of_iso: str | None = None,
) -> list[str | None]:
    """Dramatiq actor for generating reports for all repositories in an estate.

    Parameters
    ----------
    database_url
        SQLAlchemy URL for the database.
    estate_id
        The estate ID to scope repository selection.
    as_of_iso
        Optional ISO format timestamp for window computation.

    Returns
    -------
    list[str | None]
        List of report IDs generated; None entries for repos with no events.

    """
    as_of = dt.datetime.fromisoformat(as_of_iso) if as_of_iso else None

    engine = _get_or_create_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run() -> list[str | None]:
        reports = await _generate_reports_for_estate_async(
            session_factory=session_factory,
            estate_id=estate_id,
            as_of=as_of,
        )
        return [r.id if r else None for r in reports]

    return asyncio.run(run())
