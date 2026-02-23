"""Unit tests for ProjectEvidenceBundleService."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import typing as typ
from pathlib import Path

import pytest

from ghillie.catalogue.importer import CatalogueImporter
from ghillie.evidence.models import ProjectEvidenceBundle, ReportStatus
from ghillie.evidence.project_service import ProjectEvidenceBundleService
from ghillie.gold.storage import Report, ReportProject, ReportScope
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


WILDSIDE_CATALOGUE = Path("examples/wildside-catalogue.yaml")


@pytest.fixture
def _import_wildside(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Import the Wildside catalogue into the test database."""
    importer = CatalogueImporter(
        session_factory, estate_key="demo", estate_name="Demo Estate"
    )
    asyncio.run(importer.import_path(WILDSIDE_CATALOGUE, commit_sha="abc123"))


@pytest.fixture
def service(
    session_factory: async_sessionmaker[AsyncSession],
) -> ProjectEvidenceBundleService:
    """Create a ProjectEvidenceBundleService backed by the test database."""
    return ProjectEvidenceBundleService(
        catalogue_session_factory=session_factory,
        gold_session_factory=session_factory,
    )


def _estate_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Retrieve the estate ID from the database."""
    from ghillie.catalogue.storage import Estate

    async def _get() -> str:
        async with session_factory() as session:
            from sqlalchemy import select

            estate = await session.scalar(select(Estate))
            assert estate is not None
            return estate.id

    return asyncio.run(_get())


@dataclasses.dataclass
class RepositoryParams:
    """Parameters for creating a Silver Repository linked to catalogue."""

    owner: str
    name: str
    catalogue_repository_id: str
    estate_id: str


@dataclasses.dataclass
class ReportSummaryParams:
    """Parameters for creating a Gold Report machine summary."""

    status: str = "on_track"
    summary: str = "Progress is on track."
    highlights: list[str] = dataclasses.field(
        default_factory=lambda: ["Feature shipped"]
    )
    risks: list[str] = dataclasses.field(default_factory=list)
    next_steps: list[str] = dataclasses.field(default_factory=list)


def _create_silver_repo_and_report(
    session_factory: async_sessionmaker[AsyncSession],
    repo_params: RepositoryParams,
    report_params: ReportSummaryParams | None = None,
) -> None:
    """Create a Silver Repository linked to catalogue, and a Gold Report."""
    rp = report_params or ReportSummaryParams()

    async def _create() -> None:
        async with session_factory() as session:
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

            report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=silver_repo.id,
                window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                model="test-model",
                machine_summary={
                    "status": rp.status,
                    "summary": rp.summary,
                    "highlights": rp.highlights,
                    "risks": rp.risks,
                    "next_steps": rp.next_steps,
                },
            )
            session.add(report)
            await session.commit()

    asyncio.run(_create())


def _get_catalogue_repo_ids(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    """Return a dict mapping owner/name slugs to catalogue repository IDs."""
    from ghillie.catalogue.storage import RepositoryRecord

    async def _get() -> dict[str, str]:
        from sqlalchemy import select

        async with session_factory() as session:
            repos = (await session.scalars(select(RepositoryRecord))).all()
            return {f"{r.owner}/{r.name}": r.id for r in repos}

    return asyncio.run(_get())


class TestProjectEvidenceBundleService:
    """Tests for ProjectEvidenceBundleService.build_bundle()."""

    def _build_wildside_bundle(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> ProjectEvidenceBundle:
        """Build and return a bundle for the Wildside project."""
        estate_id = _estate_id(session_factory)
        return asyncio.run(service.build_bundle("wildside", estate_id))

    @pytest.mark.usefixtures("_import_wildside")
    def test_project_not_found_raises_value_error(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Requesting a nonexistent project raises ValueError."""
        estate_id = _estate_id(session_factory)

        with pytest.raises(ValueError, match="not found"):
            asyncio.run(service.build_bundle("nonexistent", estate_id))

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_contains_project_metadata(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle project metadata matches catalogue data."""
        bundle = self._build_wildside_bundle(service, session_factory)

        assert bundle.project.key == "wildside"
        assert bundle.project.name == "Wildside"
        assert bundle.project.programme == "df12"
        assert bundle.project.description is not None

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_contains_all_components(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes all components from the catalogue."""
        bundle = self._build_wildside_bundle(service, session_factory)

        assert bundle.component_count == 4
        keys = {c.key for c in bundle.components}
        assert keys == {
            "wildside-core",
            "wildside-engine",
            "wildside-mockup",
            "wildside-ingestion",
        }

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_lifecycle_stages(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Components reflect their catalogue lifecycle stages."""
        bundle = self._build_wildside_bundle(service, session_factory)

        assert len(bundle.active_components) == 3
        assert len(bundle.planned_components) == 1
        assert bundle.planned_components[0].key == "wildside-ingestion"

    @pytest.mark.usefixtures("_import_wildside")
    def test_planned_component_has_no_repository(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Planned components without repos have no repository_slug."""
        bundle = self._build_wildside_bundle(service, session_factory)

        ingestion = next(c for c in bundle.components if c.key == "wildside-ingestion")
        assert ingestion.has_repository is False
        assert ingestion.repository_summary is None
        assert ingestion.lifecycle == "planned"

    @pytest.mark.usefixtures("_import_wildside")
    def test_active_component_has_repository_slug(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Active components with repos have repository_slug populated."""
        bundle = self._build_wildside_bundle(service, session_factory)

        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.has_repository is True
        assert core.repository_slug == "leynos/wildside"

    @pytest.mark.usefixtures("_import_wildside")
    def test_component_with_report_has_summary(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Component's repository summary is populated from Gold report."""
        estate_id = _estate_id(session_factory)
        repo_ids = _get_catalogue_repo_ids(session_factory)

        _create_silver_repo_and_report(
            session_factory,
            RepositoryParams(
                owner="leynos",
                name="wildside",
                catalogue_repository_id=repo_ids["leynos/wildside"],
                estate_id=estate_id,
            ),
            ReportSummaryParams(
                status="on_track",
                summary="Good progress.",
                highlights=["Shipped v2.0"],
            ),
        )

        bundle = asyncio.run(service.build_bundle("wildside", estate_id))

        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.repository_summary is not None
        assert core.repository_summary.status == ReportStatus.ON_TRACK
        assert core.repository_summary.summary == "Good progress."
        assert "Shipped v2.0" in core.repository_summary.highlights

    @pytest.mark.usefixtures("_import_wildside")
    def test_component_without_report_has_no_summary(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Component with repo but no report has summary=None."""
        bundle = self._build_wildside_bundle(service, session_factory)

        # No Silver repos or Gold reports created, so all summaries should
        # be None even for components with catalogue repos.
        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.repository_summary is None

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_contains_dependency_edges(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes dependency edges from the component graph."""
        bundle = self._build_wildside_bundle(service, session_factory)

        assert len(bundle.dependencies) > 0
        # wildside-core depends_on wildside-engine
        core_to_engine = [
            d
            for d in bundle.dependencies
            if d.from_component == "wildside-core"
            and d.to_component == "wildside-engine"
            and d.relationship == "depends_on"
        ]
        assert len(core_to_engine) == 1
        assert core_to_engine[0].kind == "runtime"

    @pytest.mark.usefixtures("_import_wildside")
    def test_cross_project_blocked_by_edges_excluded(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Cross-project blocked_by edges are excluded from the bundle.

        wildside-engine is blocked_by ortho-config, but ortho-config
        belongs to df12-foundations. This edge should not appear in the
        Wildside project bundle.
        """
        bundle = self._build_wildside_bundle(service, session_factory)

        blocked = bundle.blocked_dependencies
        # ortho-config is in df12-foundations, not wildside, so the
        # blocked_by edge is cross-project and excluded.
        engine_blocked = [
            d
            for d in blocked
            if d.from_component == "wildside-engine"
            and d.to_component == "ortho-config"
        ]
        assert len(engine_blocked) == 0

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_contains_emits_events_to_edges(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes emits_events_to edges."""
        bundle = self._build_wildside_bundle(service, session_factory)

        emits = [d for d in bundle.dependencies if d.relationship == "emits_events_to"]
        assert len(emits) >= 1
        # wildside-core emits_events_to wildside-mockup
        core_to_mockup = [
            d
            for d in emits
            if d.from_component == "wildside-core"
            and d.to_component == "wildside-mockup"
        ]
        assert len(core_to_mockup) == 1

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_includes_previous_project_reports(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes previous project-scope reports when they exist."""
        estate_id = _estate_id(session_factory)

        # Create a previous project report
        async def _create_project_report() -> None:
            async with session_factory() as session:
                project = ReportProject(
                    key="wildside",
                    name="Wildside",
                    estate_id=estate_id,
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

        bundle = asyncio.run(service.build_bundle("wildside", estate_id))

        assert len(bundle.previous_reports) == 1
        prev = bundle.previous_reports[0]
        assert prev.status == ReportStatus.ON_TRACK
        assert "Milestone reached" in prev.highlights

    @pytest.mark.usefixtures("_import_wildside")
    def test_report_from_other_estate_excluded_from_summary(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Repository report from another estate is not attached to bundle."""
        estate_id = _estate_id(session_factory)
        repo_ids = _get_catalogue_repo_ids(session_factory)

        # Create a Silver repo + report in a *different* estate that
        # shares the same catalogue_repository_id.
        _create_silver_repo_and_report(
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

        bundle = asyncio.run(service.build_bundle("wildside", estate_id))

        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.repository_summary is None

    @pytest.mark.usefixtures("_import_wildside")
    def test_previous_reports_from_other_estate_excluded(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Previous project reports from another estate are excluded."""
        estate_id = _estate_id(session_factory)

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

        bundle = asyncio.run(service.build_bundle("wildside", estate_id))

        assert len(bundle.previous_reports) == 0

    @pytest.mark.usefixtures("_import_wildside")
    def test_bundle_generated_at_is_set(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle has a generated_at timestamp."""
        bundle = self._build_wildside_bundle(service, session_factory)

        assert bundle.generated_at is not None

    @pytest.mark.usefixtures("_import_wildside")
    def test_component_type_is_captured(
        self,
        service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Component type from catalogue is included in evidence."""
        bundle = self._build_wildside_bundle(service, session_factory)

        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.component_type == "service"

        ingestion = next(c for c in bundle.components if c.key == "wildside-ingestion")
        assert ingestion.component_type == "data-pipeline"
