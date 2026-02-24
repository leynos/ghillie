"""Shared context, helpers, and constants for project evidence BDD steps.

Extracted from ``test_project_evidence_bundle_steps.py`` to keep the
step-definition file thin and focused on scenario wiring.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

from sqlalchemy import select

from ghillie.catalogue.storage import RepositoryRecord
from tests.fixtures.specs import (
    ProjectReportParams,
    ReportSummaryParams,
    RepositoryParams,
)
from tests.unit.project_evidence_helpers import (
    _async_create_silver_repo_and_report_raw,
    create_project_report,
    get_estate_id_async,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.evidence.models import ComponentEvidence, ProjectEvidenceBundle
    from ghillie.evidence.project_service import ProjectEvidenceBundleService

WILDSIDE_CATALOGUE = "examples/wildside-catalogue.yaml"


class ProjectEvidenceContext(typ.TypedDict, total=False):
    """Mutable context dictionary shared between BDD steps.

    Attributes
    ----------
    session_factory
        Async session factory for database access.
    service
        The ``ProjectEvidenceBundleService`` under test.
    estate_id
        Estate identifier obtained after catalogue import.
    bundle
        The ``ProjectEvidenceBundle`` produced by the When step.

    """

    session_factory: async_sessionmaker[AsyncSession]
    service: ProjectEvidenceBundleService
    estate_id: str
    bundle: ProjectEvidenceBundle


async def get_estate_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Fetch the estate ID from the database."""
    return await get_estate_id_async(session_factory)


async def get_catalogue_repo_id(
    session_factory: async_sessionmaker[AsyncSession],
    owner: str,
    name: str,
) -> str:
    """Fetch a catalogue repository ID by owner/name."""
    async with session_factory() as session:
        repo = await session.scalar(
            select(RepositoryRecord).where(
                RepositoryRecord.owner == owner,
                RepositoryRecord.name == name,
            )
        )
        if repo is None:
            msg = f"Expected RepositoryRecord for {owner}/{name}"
            raise AssertionError(msg)
        return repo.id


def get_component(
    bundle: ProjectEvidenceBundle,
    component_key: str,
) -> ComponentEvidence:
    """Look up a component by key, failing with a clear message if absent.

    Parameters
    ----------
    bundle
        The project evidence bundle.
    component_key
        The component key to look up.

    Returns
    -------
    ComponentEvidence
        The matching component.

    """
    match = next((c for c in bundle.components if c.key == component_key), None)
    if match is None:
        available = [c.key for c in bundle.components]
        msg = (
            f"component {component_key!r} not found in bundle; "
            f"available keys: {available}"
        )
        raise AssertionError(msg)
    return match


def get_component_with_summary(
    bundle: ProjectEvidenceBundle,
    component_key: str,
) -> ComponentEvidence:
    """Retrieve a component and assert it has a repository summary.

    Parameters
    ----------
    bundle
        The project evidence bundle.
    component_key
        The component key to look up.

    Returns
    -------
    ComponentEvidence
        The component with a verified non-None repository_summary.

    Raises
    ------
    AssertionError
        If the component has no repository summary.

    """
    component = get_component(bundle, component_key)
    assert component.repository_summary is not None, (  # noqa: S101 — test helper; assert narrows type for callers
        f"{component_key} should have a repository summary"
    )
    return component


def create_repo_report(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Create a Silver Repository and Gold Report for leynos/wildside."""
    session_factory = project_evidence_context["session_factory"]
    estate_id = project_evidence_context["estate_id"]

    rp = ReportSummaryParams(
        status="on_track",
        summary="Good progress this week.",
        highlights=("Shipped v2.0",),
    )

    async def _create() -> None:
        cat_repo_id = await get_catalogue_repo_id(session_factory, "leynos", "wildside")
        machine_summary: dict[str, object] = {
            "status": rp.status,
            "summary": rp.summary,
            "highlights": rp.highlights,
            "risks": rp.risks,
            "next_steps": rp.next_steps,
        }
        await _async_create_silver_repo_and_report_raw(
            session_factory,
            RepositoryParams(
                owner="leynos",
                name="wildside",
                catalogue_repository_id=cat_repo_id,
                estate_id=estate_id,
            ),
            machine_summary,
        )

    asyncio.run(_create())


def create_previous_report(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Create a previous project-scope report for the Wildside project."""
    session_factory = project_evidence_context["session_factory"]
    estate_id = project_evidence_context["estate_id"]

    create_project_report(
        session_factory,
        ProjectReportParams(
            project_key="wildside",
            project_name="Wildside",
            estate_id=estate_id,
            window_start=dt.datetime(2024, 6, 24, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            highlights=("Milestone reached",),
            risks=("Dependency risk",),
        ),
    )
