"""Unit tests for ProjectEvidenceBundleService."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import pytest

from ghillie.evidence.models import ProjectEvidenceBundle, ReportStatus
from ghillie.evidence.project_service import ProjectEvidenceBundleService
from ghillie.gold.storage import Report, ReportProject, ReportScope
from tests.unit.conftest import (
    ReportSummaryParams,
    RepositoryParams,
    create_silver_repo_and_report,
    create_silver_repo_and_report_raw,
    create_silver_repo_with_multiple_reports,
    estate_id,
    get_catalogue_repo_ids,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TestStatusMappingViaBuildBundle:
    """Verify status parsing through the public ``build_bundle`` API.

    Attributes
    ----------
    None

    Notes
    -----
    Each parametrized case creates a Silver Repository and Gold Report
    whose ``machine_summary.status`` is set to the given edge-case value,
    then asserts that the resulting component summary maps it to the
    correct ``ReportStatus`` enum member.

    """

    @pytest.mark.parametrize(
        ("machine_summary_status", "expected_status"),
        [
            pytest.param(None, ReportStatus.UNKNOWN, id="none"),
            pytest.param("On_TrAcK", ReportStatus.ON_TRACK, id="mixed-case"),
            pytest.param("nonsense", ReportStatus.UNKNOWN, id="invalid-string"),
            pytest.param(123, ReportStatus.UNKNOWN, id="non-string-int"),
        ],
    )
    @pytest.mark.usefixtures("_import_wildside")
    def test_status_mapping_from_reports(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
        machine_summary_status: object,
        expected_status: ReportStatus,
    ) -> None:
        """Component summary status reflects edge-case ``machine_summary`` values.

        Parameters
        ----------
        project_evidence_service
            The service under test.
        session_factory
            Async session factory for database access.
        machine_summary_status
            Raw status value stored in the Gold Report's ``machine_summary``.
        expected_status
            The ``ReportStatus`` enum member expected after mapping.

        """
        eid = estate_id(session_factory)
        repo_ids = get_catalogue_repo_ids(session_factory)

        create_silver_repo_and_report_raw(
            session_factory,
            RepositoryParams(
                owner="leynos",
                name="wildside",
                catalogue_repository_id=repo_ids["leynos/wildside"],
                estate_id=eid,
            ),
            machine_summary={
                "status": machine_summary_status,
                "summary": "Test.",
                "highlights": [],
                "risks": [],
                "next_steps": [],
            },
        )

        bundle = asyncio.run(project_evidence_service.build_bundle("wildside", eid))
        core = next(c for c in bundle.components if c.key == "wildside-core")

        assert core.repository_summary is not None, (
            "wildside-core should have a summary"
        )
        assert core.repository_summary.status is expected_status, (
            f"expected {expected_status!r} for input {machine_summary_status!r}, "
            f"got {core.repository_summary.status!r}"
        )


class TestProjectEvidenceBundleService:
    """Tests for ProjectEvidenceBundleService.build_bundle()."""

    def _build_wildside_bundle(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ProjectEvidenceBundle:
        """Build and return a bundle for the Wildside project."""
        eid = estate_id(session_factory)
        return asyncio.run(service.build_bundle("wildside", eid))

    @pytest.mark.usefixtures("_import_wildside")
    def test_project_not_found_raises_value_error(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Requesting a nonexistent project raises ValueError."""
        eid = estate_id(session_factory)

        with pytest.raises(ValueError, match="not found"):
            asyncio.run(project_evidence_service.build_bundle("nonexistent", eid))

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_contains_project_metadata(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle project metadata matches catalogue data."""
        bundle = self._build_wildside_bundle(project_evidence_service, session_factory)

        assert bundle.project.key == "wildside", "project key mismatch"
        assert bundle.project.name == "Wildside", "project name mismatch"
        assert bundle.project.programme == "df12", "programme mismatch"
        assert bundle.project.description is not None, "description missing"

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_contains_all_components(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes all components from the catalogue."""
        bundle = self._build_wildside_bundle(project_evidence_service, session_factory)

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

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_lifecycle_stages(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Components reflect their catalogue lifecycle stages."""
        bundle = self._build_wildside_bundle(project_evidence_service, session_factory)

        assert len(bundle.active_components) == 3, (
            f"expected 3 active components, got {len(bundle.active_components)}"
        )
        assert len(bundle.planned_components) == 1, (
            f"expected 1 planned component, got {len(bundle.planned_components)}"
        )
        assert bundle.planned_components[0].key == "wildside-ingestion", (
            f"expected wildside-ingestion, got {bundle.planned_components[0].key}"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_planned_component_has_no_repository(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Planned components without repos have no repository_slug."""
        bundle = self._build_wildside_bundle(project_evidence_service, session_factory)

        ingestion = next(c for c in bundle.components if c.key == "wildside-ingestion")
        assert ingestion.has_repository is False, (
            "wildside-ingestion should lack a repository"
        )
        assert ingestion.repository_summary is None, (
            "wildside-ingestion should have no summary"
        )
        assert ingestion.lifecycle == "planned", (
            f"expected lifecycle 'planned', got {ingestion.lifecycle!r}"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_active_component_has_repository_slug(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Active components with repos have repository_slug populated."""
        bundle = self._build_wildside_bundle(project_evidence_service, session_factory)

        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.has_repository is True, "wildside-core should have a repository"
        assert core.repository_slug == "leynos/wildside", (
            f"expected leynos/wildside, got {core.repository_slug!r}"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_component_with_report_has_summary(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Component's repository summary is populated from Gold report."""
        eid = estate_id(session_factory)
        repo_ids = get_catalogue_repo_ids(session_factory)

        create_silver_repo_and_report(
            session_factory,
            RepositoryParams(
                owner="leynos",
                name="wildside",
                catalogue_repository_id=repo_ids["leynos/wildside"],
                estate_id=eid,
            ),
            ReportSummaryParams(
                status="on_track",
                summary="Good progress.",
                highlights=["Shipped v2.0"],
            ),
        )

        bundle = asyncio.run(project_evidence_service.build_bundle("wildside", eid))

        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.repository_summary is not None, (
            "wildside-core should have a summary"
        )
        assert core.repository_summary.status == ReportStatus.ON_TRACK, (
            f"expected ON_TRACK, got {core.repository_summary.status}"
        )
        assert core.repository_summary.summary == "Good progress.", (
            f"summary mismatch: {core.repository_summary.summary!r}"
        )
        assert "Shipped v2.0" in core.repository_summary.highlights, (
            f"'Shipped v2.0' not in highlights: {core.repository_summary.highlights}"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_component_repository_summary_uses_latest_report(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Repository summary uses the latest report when multiple exist.

        Creates two reports for the same repository with explicit
        generated_at timestamps and asserts only the latest one is
        reflected in the component's repository_summary.
        """
        eid = estate_id(session_factory)
        repo_ids = get_catalogue_repo_ids(session_factory)

        create_silver_repo_with_multiple_reports(
            session_factory,
            repo_params=RepositoryParams(
                owner="leynos",
                name="wildside",
                catalogue_repository_id=repo_ids["leynos/wildside"],
                estate_id=eid,
            ),
            reports=[
                (
                    dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                    dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                    dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                    "at_risk",
                    "Older report.",
                ),
                (
                    dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                    dt.datetime(2024, 7, 15, tzinfo=dt.UTC),
                    dt.datetime(2024, 7, 15, tzinfo=dt.UTC),
                    "on_track",
                    "Newer report.",
                ),
            ],
        )

        bundle = asyncio.run(project_evidence_service.build_bundle("wildside", eid))
        core = next(c for c in bundle.components if c.key == "wildside-core")

        assert core.repository_summary is not None, (
            "wildside-core should have a summary"
        )
        assert core.repository_summary.summary == "Newer report.", (
            f"expected newer report, got {core.repository_summary.summary!r}"
        )
        assert core.repository_summary.status == ReportStatus.ON_TRACK, (
            f"expected ON_TRACK, got {core.repository_summary.status}"
        )
        assert core.repository_summary.window_end == dt.datetime(
            2024, 7, 15, tzinfo=dt.UTC
        ), f"window_end mismatch: {core.repository_summary.window_end}"

    @pytest.mark.usefixtures("_import_wildside")
    def test_component_without_report_has_no_summary(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Component with repo but no report has summary=None."""
        bundle = self._build_wildside_bundle(project_evidence_service, session_factory)

        # No Silver repos or Gold reports created, so all summaries should
        # be None even for components with catalogue repos.
        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.repository_summary is None, (
            "wildside-core should have no summary without reports"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_contains_dependency_edges(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes dependency edges from the component graph."""
        bundle = self._build_wildside_bundle(project_evidence_service, session_factory)

        assert len(bundle.dependencies) > 0, "expected at least one dependency edge"
        # wildside-core depends_on wildside-engine
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
        assert core_to_engine[0].kind == "runtime", (
            f"expected kind 'runtime', got {core_to_engine[0].kind!r}"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_cross_project_blocked_by_edges_excluded(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Cross-project blocked_by edges are excluded from the bundle.

        wildside-engine is blocked_by ortho-config, but ortho-config
        belongs to df12-foundations. This edge should not appear in the
        Wildside project bundle.
        """
        bundle = self._build_wildside_bundle(project_evidence_service, session_factory)

        blocked = bundle.blocked_dependencies
        # ortho-config is in df12-foundations, not wildside, so the
        # blocked_by edge is cross-project and excluded.
        engine_blocked = [
            d
            for d in blocked
            if d.from_component == "wildside-engine"
            and d.to_component == "ortho-config"
        ]
        assert len(engine_blocked) == 0, (
            "cross-project blocked_by edges should be excluded"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_contains_emits_events_to_edges(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes emits_events_to edges."""
        bundle = self._build_wildside_bundle(project_evidence_service, session_factory)

        emits = [d for d in bundle.dependencies if d.relationship == "emits_events_to"]
        assert len(emits) >= 1, "expected at least one emits_events_to edge"
        # wildside-core emits_events_to wildside-mockup
        core_to_mockup = [
            d
            for d in emits
            if d.from_component == "wildside-core"
            and d.to_component == "wildside-mockup"
        ]
        assert len(core_to_mockup) == 1, (
            "expected one wildside-core emits_events_to wildside-mockup edge"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_includes_previous_project_reports(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes previous project-scope reports when they exist."""
        eid = estate_id(session_factory)

        # Create a previous project report
        async def _create_project_report() -> None:
            async with session_factory() as session:
                project = ReportProject(
                    key="wildside",
                    name="Wildside",
                    estate_id=eid,
                )
                report = Report(
                    scope=ReportScope.PROJECT,
                    project=project,
                    window_start=dt.datetime(2024, 6, 24, tzinfo=dt.UTC),
                    window_end=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                    model="test-model",
                    machine_summary={
                        "status": "on_track",
                        "highlights": ["Milestone reached"],
                        "risks": ["Dependency risk"],
                    },
                )
                session.add_all([project, report])
                await session.commit()

        asyncio.run(_create_project_report())

        bundle = asyncio.run(project_evidence_service.build_bundle("wildside", eid))

        assert len(bundle.previous_reports) == 1, (
            f"expected 1 previous report, got {len(bundle.previous_reports)}"
        )
        prev = bundle.previous_reports[0]
        assert prev.status == ReportStatus.ON_TRACK, (
            f"expected ON_TRACK, got {prev.status}"
        )
        assert "Milestone reached" in prev.highlights, (
            f"'Milestone reached' not in highlights: {prev.highlights}"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_previous_project_reports_limit_and_ordering(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Previous reports respect limit and descending order.

        Creates 3 project-scope reports with distinct window_end values,
        instantiates the service with max_previous_reports=2, and asserts
        that only the 2 most recent reports are returned in descending
        window_end order.
        """
        eid = estate_id(session_factory)

        async def _create_project_reports() -> None:
            async with session_factory() as session:
                project = ReportProject(
                    key="wildside",
                    name="Wildside",
                    estate_id=eid,
                )
                session.add(project)
                await session.flush()

                for month in (1, 2, 3):
                    report = Report(
                        scope=ReportScope.PROJECT,
                        project=project,
                        window_start=dt.datetime(2024, month, 1, tzinfo=dt.UTC),
                        window_end=dt.datetime(2024, month, 28, tzinfo=dt.UTC),
                        generated_at=dt.datetime(2024, month, 28, tzinfo=dt.UTC),
                        model="test-model",
                        machine_summary={
                            "status": ("on_track" if month != 1 else "at_risk"),
                            "highlights": [f"Month {month}"],
                            "risks": [],
                        },
                    )
                    session.add(report)
                await session.commit()

        asyncio.run(_create_project_reports())

        limited_service = ProjectEvidenceBundleService(
            catalogue_session_factory=session_factory,
            gold_session_factory=session_factory,
            max_previous_reports=2,
        )
        bundle = asyncio.run(limited_service.build_bundle("wildside", eid))

        assert len(bundle.previous_reports) == 2, (
            f"expected 2 previous reports, got {len(bundle.previous_reports)}"
        )
        # Most recent first (descending window_end).
        assert bundle.previous_reports[0].window_end == dt.datetime(
            2024, 3, 28, tzinfo=dt.UTC
        ), f"first report window_end mismatch: {bundle.previous_reports[0].window_end}"
        assert bundle.previous_reports[1].window_end == dt.datetime(
            2024, 2, 28, tzinfo=dt.UTC
        ), f"second report window_end mismatch: {bundle.previous_reports[1].window_end}"
        # Oldest report (month 1) should be excluded.
        window_ends = [r.window_end for r in bundle.previous_reports]
        assert dt.datetime(2024, 1, 28, tzinfo=dt.UTC) not in window_ends, (
            "oldest report (month 1) should be excluded by limit"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_report_from_other_estate_excluded_from_summary(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Repository report from another estate is not attached to bundle."""
        eid = estate_id(session_factory)
        repo_ids = get_catalogue_repo_ids(session_factory)

        # Create a Silver repo + report in a *different* estate that
        # shares the same catalogue_repository_id.
        create_silver_repo_and_report(
            session_factory,
            RepositoryParams(
                owner="leynos",
                name="wildside",
                catalogue_repository_id=repo_ids["leynos/wildside"],
                estate_id="other-estate-id",
            ),
            ReportSummaryParams(
                status="blocked",
                summary="Wrong estate report.",
            ),
        )

        bundle = asyncio.run(project_evidence_service.build_bundle("wildside", eid))

        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.repository_summary is None, (
            "report from other estate should not appear in summary"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_previous_reports_from_other_estate_excluded(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Previous project reports from another estate are excluded."""
        eid = estate_id(session_factory)

        # Create a ReportProject for "wildside" in a different estate.
        async def _create_other_estate_report() -> None:
            async with session_factory() as session:
                project = ReportProject(
                    key="wildside-other",
                    name="Wildside",
                    estate_id="other-estate-id",
                )
                report = Report(
                    scope=ReportScope.PROJECT,
                    project=project,
                    window_start=dt.datetime(2024, 6, 24, tzinfo=dt.UTC),
                    window_end=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                    model="test-model",
                    machine_summary={
                        "status": "on_track",
                        "highlights": ["Should not appear"],
                        "risks": [],
                    },
                )
                session.add_all([project, report])
                await session.commit()

        asyncio.run(_create_other_estate_report())

        bundle = asyncio.run(project_evidence_service.build_bundle("wildside", eid))

        assert len(bundle.previous_reports) == 0, (
            "reports from other estate should be excluded"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_generated_at_is_set(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle has a generated_at timestamp."""
        bundle = self._build_wildside_bundle(project_evidence_service, session_factory)

        assert bundle.generated_at is not None, (
            "bundle should have a generated_at timestamp"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_component_type_is_captured(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Component type from catalogue is included in evidence."""
        bundle = self._build_wildside_bundle(project_evidence_service, session_factory)

        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.component_type == "service", (
            f"expected component_type 'service', got {core.component_type!r}"
        )

        ingestion = next(c for c in bundle.components if c.key == "wildside-ingestion")
        assert ingestion.component_type == "data-pipeline", (
            f"expected component_type 'data-pipeline', got {ingestion.component_type!r}"
        )
