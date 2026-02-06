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
import threading
import typing as typ

import dramatiq
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ghillie.evidence import EvidenceBundleService
from ghillie.reporting._broker import ensure_broker_configured
from ghillie.reporting.config import ReportingConfig
from ghillie.reporting.errors import EstateReportError
from ghillie.reporting.service import ReportingService
from ghillie.silver.storage import Repository
from ghillie.status.factory import create_status_model

if typ.TYPE_CHECKING:
    from ghillie.gold.storage import Report

type SessionFactory = async_sessionmaker[AsyncSession]

# Module-level caches for reusing expensive resources across actor invocations
_ENGINE_CACHE: dict[str, AsyncEngine] = {}
_SESSION_FACTORY_CACHE: dict[str, SessionFactory] = {}
_SERVICE_CACHE: dict[str, ReportingService] = {}
_CACHE_LOCK = threading.Lock()

# Maximum concurrent report generations to prevent database connection exhaustion
_MAX_CONCURRENT_REPORTS = 10


def _ensure_engine(database_url: str) -> AsyncEngine:
    """Return the cached engine for *database_url*, creating it if absent.

    Precondition: the caller **must** hold ``_CACHE_LOCK``.
    """
    if database_url not in _ENGINE_CACHE:
        _ENGINE_CACHE[database_url] = create_async_engine(database_url)
    return _ENGINE_CACHE[database_url]


def _ensure_session_factory_locked(database_url: str) -> SessionFactory:
    """Return the cached session factory for *database_url*, creating it if absent.

    Precondition: the caller **must** hold ``_CACHE_LOCK``.  The session
    factory is cached alongside its engine so a single instance is shared
    across service construction and direct session usage.
    """
    if database_url not in _SESSION_FACTORY_CACHE:
        engine = _ensure_engine(database_url)
        _SESSION_FACTORY_CACHE[database_url] = async_sessionmaker(
            engine, expire_on_commit=False
        )
    return _SESSION_FACTORY_CACHE[database_url]


def _get_or_create_engine(database_url: str) -> AsyncEngine:
    """Get or create an async engine for the given database URL.

    Thread-safe: uses a lock to prevent race conditions in Dramatiq workers.
    """
    with _CACHE_LOCK:
        return _ensure_engine(database_url)


def _get_or_create_session_factory(database_url: str) -> SessionFactory:
    """Get or create an async session factory for the given database URL.

    Thread-safe: uses a lock to prevent race conditions in Dramatiq workers.
    """
    with _CACHE_LOCK:
        return _ensure_session_factory_locked(database_url)


def _get_or_create_service(database_url: str) -> ReportingService:
    """Get or create a ReportingService with cached dependencies.

    Thread-safe: uses a lock to prevent race conditions in Dramatiq workers.
    Self-contained — ensures the session factory exists before use.
    """
    with _CACHE_LOCK:
        if database_url not in _SERVICE_CACHE:
            session_factory = _ensure_session_factory_locked(database_url)
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
    service: ReportingService,
    repository_id: str,
    as_of: dt.datetime | None = None,
) -> Report | None:
    """Generate a report for a single repository (async implementation).

    Parameters
    ----------
    service
        The ReportingService to use for report generation.
    repository_id
        The Silver layer repository ID.
    as_of
        Reference time for window computation; defaults to now.

    Returns
    -------
    Report | None
        The generated report, or None if no events in window.

    """
    return await service.run_for_repository(repository_id, as_of=as_of)


def _process_gathered_results(
    gathered: list[Report | None | BaseException],
) -> list[Report | None]:
    """Process results from asyncio.gather, handling exceptions appropriately.

    Parameters
    ----------
    gathered
        List of results from asyncio.gather with return_exceptions=True.

    Returns
    -------
    list[Report | None]
        Successfully generated reports (None for repos with no events).

    Raises
    ------
    BaseException
        Re-raised immediately for system-level exceptions (e.g., KeyboardInterrupt).
    EstateReportError
        Wraps all regular Exception instances to preserve diagnostic info.

    """
    results: list[Report | None] = []
    exceptions: list[Exception] = []
    for result in gathered:
        if isinstance(result, Exception):
            exceptions.append(result)
        elif isinstance(result, BaseException):
            # Re-raise system-level exceptions (e.g., KeyboardInterrupt) immediately
            raise result
        else:
            results.append(result)

    if exceptions:
        raise EstateReportError(exceptions)

    return results


async def _generate_reports_for_estate_async(
    service: ReportingService,
    session_factory: SessionFactory,
    estate_id: str,
    as_of: dt.datetime | None = None,
) -> list[Report | None]:
    """Generate reports for all active repositories in an estate.

    Parameters
    ----------
    service
        The ReportingService to use for report generation.
    session_factory
        Async session factory for database access.
    estate_id
        The estate ID to scope repository selection.
    as_of
        Reference time for window computation; defaults to now.

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

    # Generate reports concurrently with bounded concurrency to protect DB connections
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REPORTS)

    async def bounded_report(repo_id: str) -> Report | None:
        async with semaphore:
            return await service.run_for_repository(repo_id, as_of=as_of)

    coroutines = [bounded_report(repo_id) for repo_id in repo_ids]
    gathered = await asyncio.gather(*coroutines, return_exceptions=True)

    return _process_gathered_results(gathered)


def _parse_as_of_iso(as_of_iso: str | None) -> dt.datetime | None:
    """Parse ISO timestamp string, requiring timezone information.

    Parameters
    ----------
    as_of_iso
        ISO format timestamp string, or None.

    Returns
    -------
    dt.datetime | None
        Parsed datetime with timezone, or None if input was None.

    Raises
    ------
    ValueError
        If the timestamp lacks timezone information.

    """
    if as_of_iso is None:
        return None
    parsed = dt.datetime.fromisoformat(as_of_iso)
    if parsed.tzinfo is None:
        msg = (
            f"as_of_iso must include timezone information, got naive datetime: "
            f"{as_of_iso!r}. Use ISO format with offset (e.g., '2024-07-14T10:00:00Z' "
            f"or '2024-07-14T10:00:00+00:00')."
        )
        raise ValueError(msg)
    return parsed


def _run_actor_async[T](
    database_url: str,
    as_of_iso: str | None,
    async_fn: typ.Callable[
        [ReportingService, SessionFactory, dt.datetime | None],
        typ.Awaitable[T],
    ],
) -> T:
    """Execute common async scaffolding for Dramatiq actors.

    Parameters
    ----------
    database_url
        SQLAlchemy URL for the database.
    as_of_iso
        Optional ISO format timestamp for window computation.
    async_fn
        Async function to execute with (service, session_factory, as_of) args.

    Returns
    -------
    T
        The result of async_fn.

    """
    ensure_broker_configured()
    as_of = _parse_as_of_iso(as_of_iso)

    session_factory = _get_or_create_session_factory(database_url)

    async def run() -> T:
        service = _get_or_create_service(database_url)
        return await async_fn(service, session_factory, as_of)

    return asyncio.run(run())


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
        Optional ISO format timestamp for window computation. Must include
        timezone information (e.g., '2024-07-14T10:00:00Z').

    Returns
    -------
    str | None
        The report ID if generated, or None if no events in window.

    Raises
    ------
    ValueError
        If as_of_iso is provided without timezone information.

    """

    async def execute(
        service: ReportingService,
        _session_factory: SessionFactory,
        as_of: dt.datetime | None,
    ) -> str | None:
        report = await _generate_report_async(service, repository_id, as_of=as_of)
        return report.id if report else None

    return _run_actor_async(database_url, as_of_iso, execute)


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
        Optional ISO format timestamp for window computation. Must include
        timezone information (e.g., '2024-07-14T10:00:00Z').

    Returns
    -------
    list[str | None]
        List of report IDs generated; None entries for repos with no events.

    Raises
    ------
    ValueError
        If as_of_iso is provided without timezone information.

    """

    async def execute(
        service: ReportingService,
        session_factory: SessionFactory,
        as_of: dt.datetime | None,
    ) -> list[str | None]:
        reports = await _generate_reports_for_estate_async(
            service=service,
            session_factory=session_factory,
            estate_id=estate_id,
            as_of=as_of,
        )
        return [r.id if r else None for r in reports]

    return _run_actor_async(database_url, as_of_iso, execute)
