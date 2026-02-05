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
import threading
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

type SessionFactory = async_sessionmaker[AsyncSession]

# Module-level caches for reusing expensive resources across actor invocations
_ENGINE_CACHE: dict[str, AsyncEngine] = {}
_SERVICE_CACHE: dict[str, ReportingService] = {}
_CACHE_LOCK = threading.Lock()

# Maximum concurrent report generations to prevent database connection exhaustion
_MAX_CONCURRENT_REPORTS = 10


def _get_or_create_engine(database_url: str) -> AsyncEngine:
    """Get or create an async engine for the given database URL.

    Thread-safe: uses a lock to prevent race conditions in Dramatiq workers.
    """
    with _CACHE_LOCK:
        if database_url not in _ENGINE_CACHE:
            _ENGINE_CACHE[database_url] = create_async_engine(database_url)
        return _ENGINE_CACHE[database_url]


def _get_or_create_service(
    session_factory: SessionFactory,
    database_url: str,
) -> ReportingService:
    """Get or create a ReportingService with cached dependencies.

    Thread-safe: uses a lock to prevent race conditions in Dramatiq workers.
    """
    with _CACHE_LOCK:
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
    ExceptionGroup
        Aggregates all regular Exception instances to preserve diagnostic info.

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
        raise ExceptionGroup("estate report errors", exceptions)  # noqa: TRY003

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


def _is_running_tests() -> bool:
    """Check if the current process is running in a test environment.

    Detects pytest by checking for the pytest module in sys.modules or
    pytest-specific environment variables set by pytest and pytest-xdist.

    Returns
    -------
    bool
        True if running under pytest, False otherwise.

    """
    return "pytest" in sys.modules or any(
        key in os.environ
        for key in ["PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS"]
    )


def _should_use_stub_broker() -> bool:
    """Determine whether to use a StubBroker instead of a real broker.

    Returns True if either the GHILLIE_ALLOW_STUB_BROKER environment variable
    is set to a truthy value, or if we're running in a test environment.

    Returns
    -------
    bool
        True if a StubBroker should be used, False otherwise.

    """
    allow_stub = os.environ.get("GHILLIE_ALLOW_STUB_BROKER", "")
    return allow_stub.lower() in {"1", "true", "yes"} or _is_running_tests()


def _ensure_broker_configured() -> None:
    """Ensure a Dramatiq broker is configured before actor execution.

    This function checks for an existing broker and sets up a StubBroker
    in test environments. It is called at the start of each actor function
    rather than at import time to avoid premature global state mutation.

    Raises
    ------
    RuntimeError
        If no broker is configured and we're not in a test/stub-allowed context.

    """
    try:  # pragma: no cover - exercised in tests and CLI usage
        current_broker = dramatiq.get_broker()
    except (ImportError, LookupError):
        # ImportError: broker dependencies (RabbitMQ/Redis) are not installed
        # LookupError: no broker has been configured yet
        current_broker = None

    if current_broker is None:
        if _should_use_stub_broker():
            dramatiq.set_broker(StubBroker())
        else:  # pragma: no cover - guard for prod misconfigurations
            message = (
                "No Dramatiq broker configured. Set GHILLIE_ALLOW_STUB_BROKER=1 for "
                "local/test runs or configure a real broker."
            )
            raise RuntimeError(message)


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
    _ensure_broker_configured()
    as_of = _parse_as_of_iso(as_of_iso)

    engine = _get_or_create_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def run() -> T:
        service = _get_or_create_service(session_factory, database_url)
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
