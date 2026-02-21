"""Project evidence bundle generation service.

This module provides the ProjectEvidenceBundleService class for constructing
project-level evidence bundles that aggregate catalogue metadata, component
lifecycle stages, repository report summaries, and component dependency
graphs into a single immutable structure for project-level summarisation.

The service queries two storage layers:

- **Catalogue storage** for project definitions, component records,
  repository mappings, and component dependency edges.
- **Silver/Gold storage** for Silver Repository records (linked via
  ``catalogue_repository_id``) and the latest repository-scope Gold
  reports containing machine summaries.

Results from both layers are joined in Python to avoid cross-schema SQL
joins, keeping the option of separate databases open.

Example:
-------
>>> from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
>>> from ghillie.evidence.project_service import ProjectEvidenceBundleService
>>>
>>> engine = create_async_engine("sqlite+aiosqlite:///ghillie.db")
>>> session_factory = async_sessionmaker(engine, expire_on_commit=False)
>>> service = ProjectEvidenceBundleService(session_factory, session_factory)
>>> bundle = await service.build_bundle("wildside", estate_id="estate-1")

"""

from __future__ import annotations

import typing as typ

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ghillie.catalogue.storage import (
    ComponentEdgeRecord,
    ComponentRecord,
    ProjectRecord,
)
from ghillie.common.time import utcnow
from ghillie.gold.storage import Report, ReportProject, ReportScope
from ghillie.silver.storage import Repository

from .models import (
    ComponentDependencyEvidence,
    ComponentEvidence,
    ComponentRepositorySummary,
    PreviousReportSummary,
    ProjectEvidenceBundle,
    ProjectMetadata,
    ReportStatus,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class ProjectEvidenceBundleService:
    """Generates project-level evidence bundles from catalogue and Gold data.

    This service queries catalogue storage for project metadata, component
    definitions, and dependency edges, then queries silver/gold storage for
    the latest repository-scope reports associated with each component's
    repository.

    """

    def __init__(
        self,
        catalogue_session_factory: async_sessionmaker[AsyncSession],
        gold_session_factory: async_sessionmaker[AsyncSession],
        max_previous_reports: int = 2,
    ) -> None:
        """Configure the service with session factories.

        Parameters
        ----------
        catalogue_session_factory
            Async session factory for catalogue database access.
        gold_session_factory
            Async session factory for silver/gold database access.
        max_previous_reports
            Maximum number of previous project reports to include
            for context (default 2).

        """
        self._catalogue_session_factory = catalogue_session_factory
        self._gold_session_factory = gold_session_factory
        self._max_previous_reports = max_previous_reports

    async def build_bundle(
        self,
        project_key: str,
        estate_id: str,
    ) -> ProjectEvidenceBundle:
        """Build a project evidence bundle from catalogue and report data.

        Parameters
        ----------
        project_key
            The project slug to build evidence for.
        estate_id
            The estate identifier scoping the project lookup.

        Returns
        -------
        ProjectEvidenceBundle
            Complete project evidence for status generation.

        Raises
        ------
        ValueError
            If the project is not found in the catalogue.

        """
        async with self._catalogue_session_factory() as cat_session:
            project_record = await self._fetch_project(
                cat_session, project_key, estate_id
            )
            components = project_record.components
            edges = await self._fetch_edges(cat_session, components)
            repo_slug_by_cat_id = self._collect_repo_slugs(components)

        async with self._gold_session_factory() as gold_session:
            summaries_by_cat_id = await self._fetch_latest_summaries(
                gold_session, set(repo_slug_by_cat_id.keys())
            )
            previous_reports = await self._fetch_previous_project_reports(
                gold_session, project_key
            )

        component_key_by_id = {c.id: c.key for c in components}
        component_evidence = self._build_component_evidence(
            components, repo_slug_by_cat_id, summaries_by_cat_id
        )
        dependency_evidence = self._build_dependency_evidence(
            edges, component_key_by_id
        )

        return ProjectEvidenceBundle(
            project=self._build_project_metadata(project_record),
            components=tuple(component_evidence),
            dependencies=tuple(dependency_evidence),
            previous_reports=tuple(previous_reports),
            generated_at=utcnow(),
        )

    # ------------------------------------------------------------------
    # Catalogue queries
    # ------------------------------------------------------------------

    async def _fetch_project(
        self,
        session: AsyncSession,
        project_key: str,
        estate_id: str,
    ) -> ProjectRecord:
        """Fetch a project record with eagerly loaded components."""
        stmt = (
            select(ProjectRecord)
            .where(
                ProjectRecord.key == project_key,
                ProjectRecord.estate_id == estate_id,
            )
            .options(
                selectinload(ProjectRecord.components).selectinload(
                    ComponentRecord.repository
                ),
            )
        )
        project = await session.scalar(stmt)
        if project is None:
            msg = f"Project not found: key={project_key!r}, estate_id={estate_id!r}"
            raise ValueError(msg)
        return project

    async def _fetch_edges(
        self,
        session: AsyncSession,
        components: list[ComponentRecord],
    ) -> list[ComponentEdgeRecord]:
        """Fetch all outgoing edges for the project's components."""
        component_ids = [c.id for c in components]
        if not component_ids:
            return []
        stmt = select(ComponentEdgeRecord).where(
            ComponentEdgeRecord.from_component_id.in_(component_ids)
        )
        return list((await session.scalars(stmt)).all())

    def _collect_repo_slugs(self, components: list[ComponentRecord]) -> dict[str, str]:
        """Map catalogue_repository_id to owner/name slug."""
        result: dict[str, str] = {}
        for comp in components:
            if comp.repository is not None:
                result[comp.repository.id] = comp.repository.slug
        return result

    # ------------------------------------------------------------------
    # Gold/Silver queries
    # ------------------------------------------------------------------

    async def _fetch_latest_summaries(
        self,
        session: AsyncSession,
        catalogue_repo_ids: set[str],
    ) -> dict[str, ComponentRepositorySummary]:
        """Fetch latest repo reports for each catalogue repository ID.

        Returns a dict mapping catalogue_repository_id to a
        ComponentRepositorySummary built from the latest Gold Report.

        """
        if not catalogue_repo_ids:
            return {}

        # Find Silver repositories linked to these catalogue IDs.
        repo_stmt = select(Repository).where(
            Repository.catalogue_repository_id.in_(catalogue_repo_ids)
        )
        silver_repos = list((await session.scalars(repo_stmt)).all())
        if not silver_repos:
            return {}

        # Map silver repo ID -> catalogue_repository_id for reverse lookup.
        cat_id_by_silver_id: dict[str, str] = {
            r.id: r.catalogue_repository_id
            for r in silver_repos
            if r.catalogue_repository_id is not None
        }
        silver_repo_ids = list(cat_id_by_silver_id.keys())

        # Find latest repository report for each silver repo.
        report_stmt = (
            select(Report)
            .where(
                Report.scope == ReportScope.REPOSITORY,
                Report.repository_id.in_(silver_repo_ids),
            )
            .order_by(Report.generated_at.desc())
        )
        reports = list((await session.scalars(report_stmt)).all())

        # Group by repository_id, take the latest per repo.
        latest_by_repo: dict[str, Report] = {}
        for report in reports:
            if report.repository_id is not None:
                latest_by_repo.setdefault(report.repository_id, report)

        # Build summaries keyed by catalogue_repository_id.
        result: dict[str, ComponentRepositorySummary] = {}
        for silver_repo_id, cat_repo_id in cat_id_by_silver_id.items():
            report = latest_by_repo.get(silver_repo_id)
            if report is None:
                continue
            silver_repo = next(r for r in silver_repos if r.id == silver_repo_id)
            result[cat_repo_id] = self._build_component_summary(
                report, silver_repo.slug
            )

        return result

    async def _fetch_previous_project_reports(
        self,
        session: AsyncSession,
        project_key: str,
    ) -> list[PreviousReportSummary]:
        """Fetch previous project-scope reports for context."""
        rp_stmt = select(ReportProject).where(ReportProject.key == project_key)
        report_project = await session.scalar(rp_stmt)
        if report_project is None:
            return []

        stmt = (
            select(Report)
            .where(
                Report.scope == ReportScope.PROJECT,
                Report.project_id == report_project.id,
            )
            .order_by(Report.window_end.desc())
            .limit(self._max_previous_reports)
        )
        reports = (await session.scalars(stmt)).all()

        return [self._build_previous_report_summary(r) for r in reports]

    # ------------------------------------------------------------------
    # Evidence builders
    # ------------------------------------------------------------------

    def _build_project_metadata(self, record: ProjectRecord) -> ProjectMetadata:
        """Convert ProjectRecord to ProjectMetadata struct."""
        return ProjectMetadata(
            key=record.key,
            name=record.name,
            description=record.description,
            programme=record.programme,
            documentation_paths=tuple(record.documentation_paths),
        )

    def _build_component_evidence(
        self,
        components: list[ComponentRecord],
        repo_slug_by_cat_id: dict[str, str],
        summaries_by_cat_id: dict[str, ComponentRepositorySummary],
    ) -> list[ComponentEvidence]:
        """Build ComponentEvidence structs for all components."""
        result: list[ComponentEvidence] = []
        for comp in components:
            repo_slug: str | None = None
            summary: ComponentRepositorySummary | None = None
            if comp.repository_id is not None:
                repo_slug = repo_slug_by_cat_id.get(comp.repository_id)
                summary = summaries_by_cat_id.get(comp.repository_id)

            result.append(
                ComponentEvidence(
                    key=comp.key,
                    name=comp.name,
                    component_type=comp.type,
                    lifecycle=comp.lifecycle,
                    description=comp.description,
                    repository_slug=repo_slug,
                    repository_summary=summary,
                    notes=tuple(comp.notes),
                )
            )
        return result

    def _build_dependency_evidence(
        self,
        edges: list[ComponentEdgeRecord],
        component_key_by_id: dict[str, str],
    ) -> list[ComponentDependencyEvidence]:
        """Build ComponentDependencyEvidence from edge records."""
        result: list[ComponentDependencyEvidence] = []
        for edge in edges:
            from_key = component_key_by_id.get(edge.from_component_id)
            to_key = component_key_by_id.get(edge.to_component_id)
            if from_key is None or to_key is None:
                # Cross-project edge target; skip silently.
                continue
            result.append(
                ComponentDependencyEvidence(
                    from_component=from_key,
                    to_component=to_key,
                    relationship=edge.relationship_type,
                    kind=edge.kind,
                    rationale=edge.rationale,
                )
            )
        return result

    def _build_component_summary(
        self, report: Report, slug: str
    ) -> ComponentRepositorySummary:
        """Build ComponentRepositorySummary from a Gold Report."""
        ms = report.machine_summary or {}
        return ComponentRepositorySummary(
            repository_slug=slug,
            report_id=report.id,
            window_start=report.window_start,
            window_end=report.window_end,
            status=self._parse_status(ms.get("status")),
            summary=ms.get("summary", ""),
            highlights=tuple(ms.get("highlights", [])),
            risks=tuple(ms.get("risks", [])),
            next_steps=tuple(ms.get("next_steps", [])),
            generated_at=report.generated_at,
        )

    def _build_previous_report_summary(self, report: Report) -> PreviousReportSummary:
        """Build PreviousReportSummary from a Gold project Report."""
        ms = report.machine_summary or {}
        return PreviousReportSummary(
            report_id=report.id,
            window_start=report.window_start,
            window_end=report.window_end,
            status=self._parse_status(ms.get("status")),
            highlights=tuple(ms.get("highlights", [])),
            risks=tuple(ms.get("risks", [])),
        )

    def _parse_status(self, status: typ.Any) -> ReportStatus:  # noqa: ANN401
        """Parse status string into ReportStatus enum."""
        match status:
            case None:
                return ReportStatus.UNKNOWN
            case str() as s:
                try:
                    return ReportStatus(s.lower())
                except ValueError:
                    return ReportStatus.UNKNOWN
            case _:
                try:
                    return ReportStatus(str(status).lower())
                except ValueError:
                    return ReportStatus.UNKNOWN
