"""Project evidence fixtures and helper functions.

Extracted from ``tests/unit/conftest.py`` to keep the shared conftest
focused on general-purpose fixtures.

Examples
--------
Import helpers for use in a test module::

    from tests.unit.project_evidence_helpers import (
        create_silver_repo_and_report,
        get_estate_id,
    )

"""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import pytest
import pytest_asyncio
from sqlalchemy import select

from ghillie.catalogue.importer import CatalogueImporter
from ghillie.catalogue.storage import Estate, RepositoryRecord
from ghillie.evidence.project_service import ProjectEvidenceBundleService
from ghillie.gold.storage import Report, ReportProject, ReportScope
from ghillie.silver.storage import Repository
from tests.fixtures.specs import (
    ProjectReportParams,
    ReportSpec,
    ReportSummaryParams,
    RepositoryParams,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def _import_wildside(
    session_factory: async_sessionmaker[AsyncSession],
    wildside_catalogue_path: Path,
) -> None:
    """Import the Wildside catalogue into the test database."""
    importer = CatalogueImporter(
        session_factory, estate_key="demo", estate_name="Demo Estate"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="abc123")


@pytest.fixture
def project_evidence_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> ProjectEvidenceBundleService:
    """Create a ProjectEvidenceBundleService backed by the test database."""
    return ProjectEvidenceBundleService(
        catalogue_session_factory=session_factory,
        gold_session_factory=session_factory,
    )


# ---------------------------------------------------------------------------
# Private async helpers
# ---------------------------------------------------------------------------


async def _insert_silver_repo(
    session: AsyncSession,
    repo_params: RepositoryParams,
) -> Repository:
    """Create a Silver Repository row and flush, returning the new row."""
    silver_repo = Repository(
        github_owner=repo_params.owner,
        github_name=repo_params.name,
        default_branch="main",
        estate_id=repo_params.estate_id,
        catalogue_repository_id=repo_params.catalogue_repository_id,
        ingestion_enabled=True,
    )
    session.add(silver_repo)
    await session.flush()
    return silver_repo


async def _async_get_estate_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Retrieve the estate ID from the database (async)."""
    async with session_factory() as session:
        est = await session.scalar(select(Estate))
        if est is None:
            msg = "expected an Estate record in DB"
            raise AssertionError(msg)
        return est.id


async def _async_get_catalogue_repo_ids(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    """Return a dict mapping owner/name slugs to catalogue repository IDs (async)."""
    async with session_factory() as session:
        repos = (await session.scalars(select(RepositoryRecord))).all()
        return {f"{r.owner}/{r.name}": r.id for r in repos}


async def _async_create_silver_repo_with_multiple_reports(
    session_factory: async_sessionmaker[AsyncSession],
    repo_params: RepositoryParams,
    reports: cabc.Sequence[ReportSpec],
) -> None:
    """Create a Silver Repository with multiple Gold Reports (async)."""
    async with session_factory() as session:
        silver_repo = await _insert_silver_repo(session, repo_params)
        report_objects = []
        for spec in reports:
            report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=silver_repo.id,
                window_start=spec.window_start,
                window_end=spec.window_end,
                generated_at=spec.generated_at,
                model="test-model",
                machine_summary={
                    "status": spec.status,
                    "summary": spec.summary,
                    "highlights": [],
                    "risks": [],
                    "next_steps": [],
                },
            )
            report_objects.append(report)
        session.add_all(report_objects)
        await session.commit()


async def _async_create_silver_repo_and_report_raw(
    session_factory: async_sessionmaker[AsyncSession],
    repo_params: RepositoryParams,
    machine_summary: dict[str, object],
) -> None:
    """Create a Silver Repository and Gold Report with arbitrary summary (async)."""
    async with session_factory() as session:
        silver_repo = await _insert_silver_repo(session, repo_params)
        report = Report(
            scope=ReportScope.REPOSITORY,
            repository_id=silver_repo.id,
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            model="test-model",
            machine_summary=machine_summary,
        )
        session.add(report)
        await session.commit()


async def _async_create_project_report(
    session_factory: async_sessionmaker[AsyncSession],
    params: ProjectReportParams,
) -> None:
    """Create a ReportProject if needed and a project-scope Gold Report (async)."""
    async with session_factory() as session:
        project = await session.scalar(
            select(ReportProject).where(
                ReportProject.key == params.project_key,
                ReportProject.estate_id == params.estate_id,
            )
        )
        if project is None:
            project = ReportProject(
                key=params.project_key,
                name=params.project_name,
                estate_id=params.estate_id,
            )
            session.add(project)
            await session.flush()

        report = Report(
            scope=ReportScope.PROJECT,
            project=project,
            window_start=params.window_start,
            window_end=params.window_end,
            generated_at=params.generated_at,
            model="test-model",
            machine_summary={
                "status": params.status,
                "highlights": list(params.highlights),
                "risks": list(params.risks),
            },
        )
        session.add(report)
        await session.commit()


# ---------------------------------------------------------------------------
# Synchronous convenience wrappers (use asyncio.run)
# ---------------------------------------------------------------------------


async def get_estate_id_async(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Retrieve the estate ID from the database (async).

    Delegates to :func:`_async_get_estate_id`.  Use this variant inside
    async test code or BDD helpers that already have an event loop.

    Parameters
    ----------
    session_factory
        Async session factory for database access.

    Returns
    -------
    str
        The estate identifier.

    """
    return await _async_get_estate_id(session_factory)


def get_estate_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Retrieve the estate ID from the database.

    Calls :func:`asyncio.run` internally; use :func:`get_estate_id_async`
    when an event loop is already running.

    Parameters
    ----------
    session_factory
        Async session factory for database access.

    Returns
    -------
    str
        The estate identifier.

    """
    return asyncio.run(_async_get_estate_id(session_factory))


def get_catalogue_repo_ids(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    """Return a dict mapping owner/name slugs to catalogue repository IDs.

    Parameters
    ----------
    session_factory
        Async session factory for database access.

    Returns
    -------
    dict[str, str]
        Mapping of ``"owner/name"`` slugs to catalogue repository IDs.

    """
    return asyncio.run(_async_get_catalogue_repo_ids(session_factory))


def create_silver_repo_and_report(
    session_factory: async_sessionmaker[AsyncSession],
    repo_params: RepositoryParams,
    report_params: ReportSummaryParams | None = None,
) -> None:
    """Create a Silver Repository linked to catalogue, and a Gold Report.

    Parameters
    ----------
    session_factory
        Async session factory for database access.
    repo_params
        Repository creation parameters.
    report_params
        Report summary parameters.  Defaults to ``ReportSummaryParams()``
        when *None*.

    """
    rp = report_params or ReportSummaryParams()
    machine_summary: dict[str, object] = {
        "status": rp.status,
        "summary": rp.summary,
        "highlights": rp.highlights,
        "risks": rp.risks,
        "next_steps": rp.next_steps,
    }
    create_silver_repo_and_report_raw(session_factory, repo_params, machine_summary)


def create_silver_repo_with_multiple_reports(
    session_factory: async_sessionmaker[AsyncSession],
    repo_params: RepositoryParams,
    reports: cabc.Sequence[ReportSpec],
) -> None:
    """Create a Silver Repository with multiple Gold Reports.

    Parameters
    ----------
    session_factory
        Async session factory for database access.
    repo_params
        Repository creation parameters.
    reports
        List of report specifications to create.

    """
    asyncio.run(
        _async_create_silver_repo_with_multiple_reports(
            session_factory, repo_params, reports
        )
    )


def create_silver_repo_and_report_raw(
    session_factory: async_sessionmaker[AsyncSession],
    repo_params: RepositoryParams,
    machine_summary: dict[str, object],
) -> None:
    """Create a Silver Repository and Gold Report with an arbitrary summary.

    Parameters
    ----------
    session_factory
        Async session factory for database access.
    repo_params
        Repository creation parameters.
    machine_summary
        Verbatim dict stored on the Gold Report's ``machine_summary``.

    """
    asyncio.run(
        _async_create_silver_repo_and_report_raw(
            session_factory, repo_params, machine_summary
        )
    )


def create_project_report(
    session_factory: async_sessionmaker[AsyncSession],
    params: ProjectReportParams,
) -> None:
    """Create a ReportProject (if needed) and a project-scope Gold Report.

    Re-uses an existing ``ReportProject`` when one with the given
    *project_key* and *estate_id* already exists, allowing multiple
    reports for the same project across successive calls.

    Parameters
    ----------
    session_factory
        Async session factory for database access.
    params
        Project report creation parameters.

    """
    asyncio.run(_async_create_project_report(session_factory, params))
