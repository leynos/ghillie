"""Unit tests for project evidence repository summaries and previous reports."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import pytest

from ghillie.evidence.models import ReportStatus
from ghillie.evidence.project_service import ProjectEvidenceBundleService
from tests.fixtures.specs import (
    ProjectReportParams,
    ReportSpec,
    ReportSummaryParams,
    RepositoryParams,
)
from tests.unit.project_evidence_helpers import (
    create_project_report,
    create_silver_repo_and_report,
    create_silver_repo_with_multiple_reports,
    get_catalogue_repo_ids,
    get_estate_id,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.evidence.models import ProjectEvidenceBundle


def _build_wildside_bundle(
    service: ProjectEvidenceBundleService,
    session_factory: async_sessionmaker[AsyncSession],
) -> ProjectEvidenceBundle:
    """Build and return a bundle for the Wildside project."""
    eid = get_estate_id(session_factory)
    return asyncio.run(service.build_bundle("wildside", eid))


class TestProjectEvidenceReports:
    """Tests for repository summaries, previous reports, and estate filtering."""

    @pytest.mark.usefixtures("_import_wildside")
    def test_component_with_report_has_summary(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Component's repository summary is populated from Gold report."""
        eid = get_estate_id(session_factory)
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
                highlights=("Shipped v2.0",),
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
        eid = get_estate_id(session_factory)
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
                ReportSpec(
                    window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                    window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                    generated_at=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                    status="at_risk",
                    summary="Older report.",
                ),
                ReportSpec(
                    window_start=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                    window_end=dt.datetime(2024, 7, 15, tzinfo=dt.UTC),
                    generated_at=dt.datetime(2024, 7, 15, tzinfo=dt.UTC),
                    status="on_track",
                    summary="Newer report.",
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
        bundle = _build_wildside_bundle(project_evidence_service, session_factory)

        # No Silver repos or Gold reports created, so all summaries should
        # be None even for components with catalogue repos.
        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.repository_summary is None, (
            "wildside-core should have no summary without reports"
        )

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_includes_previous_project_reports(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes previous project-scope reports when they exist."""
        eid = get_estate_id(session_factory)

        create_project_report(
            session_factory,
            ProjectReportParams(
                project_key="wildside",
                project_name="Wildside",
                estate_id=eid,
                window_start=dt.datetime(2024, 6, 24, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                highlights=("Milestone reached",),
                risks=("Dependency risk",),
            ),
        )

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
        eid = get_estate_id(session_factory)

        for month in (1, 2, 3):
            create_project_report(
                session_factory,
                ProjectReportParams(
                    project_key="wildside",
                    project_name="Wildside",
                    estate_id=eid,
                    window_start=dt.datetime(2024, month, 1, tzinfo=dt.UTC),
                    window_end=dt.datetime(2024, month, 28, tzinfo=dt.UTC),
                    generated_at=dt.datetime(2024, month, 28, tzinfo=dt.UTC),
                    status="at_risk" if month == 1 else "on_track",
                    highlights=(f"Month {month}",),
                ),
            )

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
        eid = get_estate_id(session_factory)
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
        eid = get_estate_id(session_factory)

        # Create a ReportProject for "wildside" in a different estate.
        create_project_report(
            session_factory,
            ProjectReportParams(
                project_key="wildside",
                project_name="Wildside",
                estate_id="other-estate-id",
                window_start=dt.datetime(2024, 6, 24, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                highlights=("Should not appear",),
            ),
        )

        bundle = asyncio.run(project_evidence_service.build_bundle("wildside", eid))

        assert len(bundle.previous_reports) == 0, (
            "reports from other estate should be excluded"
        )
