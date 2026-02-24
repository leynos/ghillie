"""Behavioural tests for project evidence bundle generation.

This module implements pytest-bdd step definitions for the project evidence
bundle feature file (``project_evidence_bundle.feature``).  The scenarios
exercise end-to-end bundle construction: importing a catalogue, creating
Silver repositories and Gold reports, building a bundle, and asserting that
the resulting ``ProjectEvidenceBundle`` contains expected metadata,
components, dependency edges, repository summaries, and previous report
context.

Scenarios
---------
- Build project evidence bundle for multi-component project
- Bundle includes component with latest repository summary
- Bundle includes planned component without repository
- Bundle includes previous project report context

Fixtures
--------
session_factory
    Async session factory provided by the ``conftest`` database fixture.
project_evidence_context
    A ``ProjectEvidenceContext`` TypedDict populated by Given steps and
    threaded through When/Then steps.

Examples
--------
Run all project evidence bundle scenarios::

    pytest tests/features/steps/test_project_evidence_bundle_steps.py -v

"""

from __future__ import annotations

import asyncio
import typing as typ

from pytest_bdd import given, scenario, then, when

from ghillie.catalogue.importer import CatalogueImporter
from ghillie.evidence.models import ReportStatus
from ghillie.evidence.project_service import ProjectEvidenceBundleService
from tests.features.steps._project_evidence_context import (
    WILDSIDE_CATALOGUE,
    ProjectEvidenceContext,
    create_previous_report,
    create_repo_report,
    get_component_with_summary,
    get_estate_id,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


# Scenario wrappers


@scenario(
    "../project_evidence_bundle.feature",
    "Build project evidence bundle for multi-component project",
)
def test_build_project_evidence_bundle_scenario() -> None:
    """Verify bundle construction for a multi-component catalogue project.

    Asserts that the bundle contains correct project metadata, all four
    Wildside components, and intra-project dependency edges while
    excluding cross-project edges.

    """


@scenario(
    "../project_evidence_bundle.feature",
    "Bundle includes component with latest repository summary",
)
def test_bundle_with_repo_summary_scenario() -> None:
    """Verify a component's repository summary is populated from a Gold report.

    Creates a Silver repository and Gold report for ``leynos/wildside``,
    then asserts that the corresponding component carries the report
    summary with correct status and text.

    """


@scenario(
    "../project_evidence_bundle.feature",
    "Bundle includes planned component without repository",
)
def test_planned_component_scenario() -> None:
    """Verify a planned component has no repository or summary.

    Asserts that the ``wildside-ingestion`` component has lifecycle
    ``planned``, no repository slug, and no repository summary.

    """


@scenario(
    "../project_evidence_bundle.feature",
    "Bundle includes previous project report context",
)
def test_previous_project_report_scenario() -> None:
    """Verify previous project-scope reports appear in the bundle.

    Creates a previous project report and asserts it is included in
    ``bundle.previous_reports`` with the expected status and highlights.

    """


# Given steps


@given(
    "an imported catalogue with a multi-component project",
    target_fixture="project_evidence_context",
)
def given_imported_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
) -> ProjectEvidenceContext:
    """Import the Wildside catalogue and provision services.

    Parameters
    ----------
    session_factory
        Async session factory provided by the database fixture.

    Returns
    -------
    ProjectEvidenceContext
        Context dictionary with ``session_factory``, ``service``, and
        ``estate_id`` populated.

    """
    from pathlib import Path

    importer = CatalogueImporter(
        session_factory, estate_key="demo", estate_name="Demo Estate"
    )
    asyncio.run(importer.import_path(Path(WILDSIDE_CATALOGUE), commit_sha="abc123"))

    estate_id = asyncio.run(get_estate_id(session_factory))

    return {
        "session_factory": session_factory,
        "service": ProjectEvidenceBundleService(
            catalogue_session_factory=session_factory,
            gold_session_factory=session_factory,
        ),
        "estate_id": estate_id,
    }


@given('a repository report exists for "leynos/wildside"')
def given_repo_report_exists(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Create a Silver Repository and Gold Report for leynos/wildside.

    Parameters
    ----------
    project_evidence_context
        Shared step context containing the session factory and estate ID.

    """
    create_repo_report(project_evidence_context)


@given('a previous project report exists for "wildside"')
def given_previous_project_report(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Create a previous project-scope report for the Wildside project.

    Parameters
    ----------
    project_evidence_context
        Shared step context containing the session factory and estate ID.

    """
    create_previous_report(project_evidence_context)


# When steps


@when('I build a project evidence bundle for "wildside"')
def when_build_bundle(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Build the project evidence bundle for the Wildside project.

    Parameters
    ----------
    project_evidence_context
        Shared step context containing the service and estate ID.

    """
    service = project_evidence_context["service"]
    estate_id = project_evidence_context["estate_id"]

    bundle = asyncio.run(service.build_bundle("wildside", estate_id))
    project_evidence_context["bundle"] = bundle


# Then steps


@then("the bundle contains the project metadata")
def then_bundle_has_project_metadata(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Assert the bundle contains correct project metadata.

    Parameters
    ----------
    project_evidence_context
        Shared step context containing the built bundle.

    """
    bundle = project_evidence_context["bundle"]

    assert bundle.project.key == "wildside", "project key mismatch"
    assert bundle.project.name == "Wildside", "project name mismatch"
    assert bundle.project.programme == "df12", "programme mismatch"
    assert bundle.project.description is not None, "description missing"


@then("the bundle contains all four components")
def then_bundle_has_four_components(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Assert the bundle contains all four Wildside components.

    Parameters
    ----------
    project_evidence_context
        Shared step context containing the built bundle.

    """
    bundle = project_evidence_context["bundle"]

    assert bundle.component_count == 4, (
        f"expected 4 components, got {bundle.component_count}"
    )
    keys = {c.key for c in bundle.components}
    assert keys == {
        "wildside-core",
        "wildside-engine",
        "wildside-mockup",
        "wildside-ingestion",
    }, f"unexpected component keys: {keys}"


@then("the bundle contains intra-project dependency edges")
def then_bundle_has_dependency_edges(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Assert the bundle contains intra-project dependency edges only.

    Parameters
    ----------
    project_evidence_context
        Shared step context containing the built bundle.

    """
    bundle = project_evidence_context["bundle"]

    assert bundle.dependencies, "Expected at least one dependency edge"

    # wildside-core depends_on wildside-engine (intra-project)
    core_to_engine = [
        d
        for d in bundle.dependencies
        if d.from_component == "wildside-core"
        and d.to_component == "wildside-engine"
        and d.relationship == "depends_on"
    ]
    assert len(core_to_engine) == 1, (
        "expected one wildside-core depends_on wildside-engine edge"
    )

    # Cross-project edges must be excluded (e.g. ortho-config belongs to
    # df12-foundations, not wildside).
    assert all(dep.to_component != "ortho-config" for dep in bundle.dependencies), (
        "Bundle should not contain cross-project dependency edges to ortho-config"
    )


@then('the component "wildside-core" has a repository summary')
def then_core_has_summary(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Assert wildside-core has a repository summary from its Gold report.

    Parameters
    ----------
    project_evidence_context
        Shared step context containing the built bundle.

    """
    bundle = project_evidence_context["bundle"]
    core = get_component_with_summary(bundle, "wildside-core")
    # type-narrow: get_component_with_summary ensures repository_summary is not None
    summary = core.repository_summary
    assert summary is not None

    assert summary.summary == "Good progress this week.", (
        f"summary text mismatch: {summary.summary!r}"
    )


@then('the repository summary status is "on_track"')
def then_summary_status_on_track(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Assert the repository summary status is ``on_track``.

    Parameters
    ----------
    project_evidence_context
        Shared step context containing the built bundle.

    """
    bundle = project_evidence_context["bundle"]
    core = get_component_with_summary(bundle, "wildside-core")
    # type-narrow: get_component_with_summary ensures repository_summary is not None
    summary = core.repository_summary
    assert summary is not None

    assert summary.status == ReportStatus.ON_TRACK, (
        f"expected ON_TRACK, got {summary.status}"
    )


@then('the component "wildside-ingestion" has no repository')
def then_ingestion_has_no_repo(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Assert wildside-ingestion has no repository or summary.

    Parameters
    ----------
    project_evidence_context
        Shared step context containing the built bundle.

    """
    bundle = project_evidence_context["bundle"]

    ingestion = next(c for c in bundle.components if c.key == "wildside-ingestion")
    assert ingestion.has_repository is False, (
        "wildside-ingestion should have no repository"
    )
    assert ingestion.repository_summary is None, (
        "wildside-ingestion should have no summary"
    )


@then('the component "wildside-ingestion" has lifecycle "planned"')
def then_ingestion_is_planned(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Assert wildside-ingestion lifecycle is ``planned``.

    Parameters
    ----------
    project_evidence_context
        Shared step context containing the built bundle.

    """
    bundle = project_evidence_context["bundle"]

    ingestion = next(c for c in bundle.components if c.key == "wildside-ingestion")
    assert ingestion.lifecycle == "planned", (
        f"expected lifecycle 'planned', got {ingestion.lifecycle!r}"
    )


@then("the bundle contains the previous project report summary")
def then_bundle_has_previous_report(
    project_evidence_context: ProjectEvidenceContext,
) -> None:
    """Assert the bundle contains the previous project report summary.

    Parameters
    ----------
    project_evidence_context
        Shared step context containing the built bundle.

    """
    bundle = project_evidence_context["bundle"]

    assert len(bundle.previous_reports) == 1, (
        f"expected 1 previous report, got {len(bundle.previous_reports)}"
    )
    prev = bundle.previous_reports[0]
    assert prev.status == ReportStatus.ON_TRACK, f"expected ON_TRACK, got {prev.status}"
    assert "Milestone reached" in prev.highlights, (
        f"expected 'Milestone reached' in highlights: {prev.highlights}"
    )
