"""Catalogue importer and reconciler.

The importer watches a version-controlled catalogue file and reconciles its
projects, components, repositories, and component edges into relational
tables. Reconciliation is idempotent and wrapped in a single transaction so a
failing catalogue cannot partially update state.
"""

from __future__ import annotations

import asyncio
import dataclasses
import typing as typ
from pathlib import Path

import dramatiq
import msgspec
from dramatiq.brokers.stub import StubBroker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload

from .loader import load_catalogue
from .storage import (
    CatalogueImportRecord,
    ComponentEdgeRecord,
    ComponentRecord,
    Estate,
    ProjectRecord,
    RepositoryRecord,
    init_catalogue_storage,
)

if typ.TYPE_CHECKING:
    from .models import Catalogue, Component, ComponentLink

SessionFactory = async_sessionmaker[AsyncSession]


@dataclasses.dataclass(slots=True)
class CatalogueImportResult:
    """Summary of a catalogue reconciliation run."""

    estate_key: str
    commit_sha: str | None
    projects_created: int = 0
    projects_updated: int = 0
    projects_deleted: int = 0
    components_created: int = 0
    components_updated: int = 0
    components_deleted: int = 0
    repositories_created: int = 0
    repositories_updated: int = 0
    repositories_deleted: int = 0
    edges_created: int = 0
    edges_updated: int = 0
    edges_deleted: int = 0
    skipped: bool = False


def _set_if_changed(model: object, attr: str, value: object) -> bool:
    current = getattr(model, attr)
    if current == value:
        return False
    setattr(model, attr, value)
    return True


class CatalogueImporter:
    """Import catalogue files into the persistence layer."""

    def __init__(
        self,
        session_factory: SessionFactory | typ.Callable[[], AsyncSession],
        *,
        estate_key: str = "default",
        estate_name: str | None = None,
    ) -> None:
        """Configure importer with the session factory and estate identity."""
        self._session_factory = session_factory
        self.estate_key = estate_key
        self.estate_name = estate_name or estate_key

    async def import_path(
        self, catalogue_path: Path, *, commit_sha: str | None = None
    ) -> CatalogueImportResult:
        """Load and import a catalogue file from disk."""
        catalogue = load_catalogue(catalogue_path)
        return await self.import_catalogue(catalogue, commit_sha=commit_sha)

    async def import_catalogue(
        self, catalogue: Catalogue, *, commit_sha: str | None = None
    ) -> CatalogueImportResult:
        """Validate and reconcile an in-memory catalogue instance."""
        result = CatalogueImportResult(self.estate_key, commit_sha)

        async with self._session_factory() as session, session.begin():  # type: ignore[call-arg]
            estate = await self._ensure_estate(session)
            existing_import = None
            if commit_sha:
                existing_import = await session.scalar(
                    select(CatalogueImportRecord).where(
                        CatalogueImportRecord.commit_sha == commit_sha
                    )
                )
                if existing_import:
                    result.skipped = True

            project_index = await self._reconcile_projects(
                session, estate, catalogue, result
            )
            component_index = await self._reconcile_components(
                session, project_index, catalogue, result
            )
            await self._reconcile_edges(session, component_index, catalogue, result)

            if commit_sha and existing_import is None:
                session.add(
                    CatalogueImportRecord(
                        estate_id=estate.id,
                        commit_sha=commit_sha,
                    )
                )

        return result

    def run_sync(
        self, catalogue_path: Path, *, commit_sha: str | None = None
    ) -> CatalogueImportResult:
        """Run the importer synchronously for blocking contexts."""
        return asyncio.run(self.import_path(catalogue_path, commit_sha=commit_sha))

    async def _ensure_estate(self, session: AsyncSession) -> Estate:
        estate = await session.scalar(
            select(Estate).where(Estate.key == self.estate_key)
        )
        if estate:
            if _set_if_changed(estate, "name", self.estate_name):
                _set_if_changed(estate, "description", None)
            return estate

        estate = Estate(key=self.estate_key, name=self.estate_name)
        session.add(estate)
        await session.flush()
        return estate

    async def _reconcile_projects(
        self,
        session: AsyncSession,
        estate: Estate,
        catalogue: Catalogue,
        result: CatalogueImportResult,
    ) -> dict[str, ProjectRecord]:
        existing_projects = {
            project.key: project
            for project in (
                await session.scalars(
                    select(ProjectRecord)
                    .where(ProjectRecord.estate_id == estate.id)
                    .options(
                        selectinload(ProjectRecord.components).selectinload(
                            ComponentRecord.repository
                        )
                    )
                )
            ).all()
        }

        seen_keys: set[str] = set()
        for project in catalogue.projects:
            seen_keys.add(project.key)
            if project.key in existing_projects:
                record = existing_projects[project.key]
                changed = False
                changed |= _set_if_changed(record, "name", project.name)
                changed |= _set_if_changed(record, "description", project.description)
                changed |= _set_if_changed(record, "programme", project.programme)
                changed |= _set_if_changed(
                    record, "noise", msgspec.structs.asdict(project.noise)
                )
                changed |= _set_if_changed(
                    record,
                    "status_preferences",
                    msgspec.structs.asdict(project.status),
                )
                changed |= _set_if_changed(
                    record, "documentation_paths", project.documentation_paths
                )
                if changed:
                    result.projects_updated += 1
            else:
                record = ProjectRecord(
                    estate_id=estate.id,
                    key=project.key,
                    name=project.name,
                    description=project.description,
                    programme=project.programme,
                    noise=msgspec.structs.asdict(project.noise),
                    status_preferences=msgspec.structs.asdict(project.status),
                    documentation_paths=project.documentation_paths,
                )
                session.add(record)
                existing_projects[project.key] = record
                result.projects_created += 1

        for key, record in list(existing_projects.items()):
            if key not in seen_keys:
                await session.delete(record)
                result.projects_deleted += 1
                existing_projects.pop(key, None)

        return existing_projects

    async def _reconcile_components(
        self,
        session: AsyncSession,
        project_index: dict[str, ProjectRecord],
        catalogue: Catalogue,
        result: CatalogueImportResult,
    ) -> dict[str, ComponentRecord]:
        repo_index = {
            repo.slug: repo
            for repo in (await session.scalars(select(RepositoryRecord))).all()
        }
        self._existing_repo_ids = {repo.id for repo in repo_index.values()}

        component_index: dict[str, ComponentRecord] = {}

        for project in catalogue.projects:
            record = project_index[project.key]
            existing_components = {
                component.key: component
                for component in (
                    await session.scalars(
                        select(ComponentRecord)
                        .where(ComponentRecord.project_id == record.id)
                        .options(
                            selectinload(ComponentRecord.repository),
                            selectinload(ComponentRecord.outgoing_edges),
                        )
                    )
                ).all()
            }

            seen_components: set[str] = set()
            for component in project.components:
                seen_components.add(component.key)
                repository_record = self._ensure_repository(
                    session, repo_index, component, result
                )

                if component.key in existing_components:
                    comp_record = existing_components[component.key]
                    changed = False
                    changed |= _set_if_changed(comp_record, "name", component.name)
                    changed |= _set_if_changed(comp_record, "type", component.type)
                    changed |= _set_if_changed(
                        comp_record, "lifecycle", component.lifecycle
                    )
                    changed |= _set_if_changed(
                        comp_record, "description", component.description
                    )
                    changed |= _set_if_changed(
                        comp_record, "notes", list(component.notes)
                    )
                    changed |= _set_if_changed(
                        comp_record,
                        "repository_id",
                        repository_record.id if repository_record else None,
                    )
                    if changed:
                        result.components_updated += 1
                else:
                    comp_record = ComponentRecord(
                        project_id=record.id,
                        repository_id=(
                            repository_record.id if repository_record else None
                        ),
                        key=component.key,
                        name=component.name,
                        type=component.type,
                        lifecycle=component.lifecycle,
                        description=component.description,
                        notes=list(component.notes),
                    )
                    session.add(comp_record)
                    result.components_created += 1
                    existing_components[component.key] = comp_record

                component_index[component.key] = comp_record

            for key, comp_record in list(existing_components.items()):
                if key not in seen_components:
                    await session.delete(comp_record)
                    result.components_deleted += 1
                    existing_components.pop(key, None)

        await self._prune_unreferenced_repositories(
            session,
            repo_index,
            component_index,
            result,
        )

        return component_index

    def _ensure_repository(
        self,
        session: AsyncSession,
        repo_index: dict[str, RepositoryRecord],
        component: Component,
        result: CatalogueImportResult,
    ) -> RepositoryRecord | None:
        if component.repository is None:
            return None

        slug = component.repository.slug
        repository = repo_index.get(slug)
        if repository is None:
            repository = RepositoryRecord(
                owner=component.repository.owner,
                name=component.repository.name,
                default_branch=component.repository.default_branch,
            )
            session.add(repository)
            repo_index[slug] = repository
            result.repositories_created += 1
            return repository

        changed = False
        changed |= _set_if_changed(
            repository, "default_branch", component.repository.default_branch
        )
        if changed:
            result.repositories_updated += 1
        return repository

    async def _prune_unreferenced_repositories(
        self,
        session: AsyncSession,
        repo_index: dict[str, RepositoryRecord],
        component_index: dict[str, ComponentRecord],
        result: CatalogueImportResult,
    ) -> None:
        existing_repo_ids = getattr(self, "_existing_repo_ids", set())
        desired_repo_ids = {
            comp.repository_id
            for comp in component_index.values()
            if comp.repository_id
        }
        for slug, repository in list(repo_index.items()):
            if (
                repository.id in existing_repo_ids
                and repository.id not in desired_repo_ids
            ):
                await session.delete(repository)
                result.repositories_deleted += 1
                repo_index.pop(slug, None)

    async def _load_existing_edges(
        self,
        session: AsyncSession,
        component_ids: set[str],
    ) -> dict[tuple[str, str, str], ComponentEdgeRecord]:
        edges = await session.scalars(
            select(ComponentEdgeRecord).where(
                ComponentEdgeRecord.from_component_id.in_(component_ids)
            )
        )
        return {
            (
                edge.from_component_id,
                edge.to_component_id,
                edge.relationship_type,
            ): edge
            for edge in edges.all()
        }

    def _build_desired_edges(
        self,
        component_index: dict[str, ComponentRecord],
        catalogue: Catalogue,
    ) -> dict[tuple[str, str, str], ComponentLink]:
        desired_edges: dict[tuple[str, str, str], ComponentLink] = {}
        for project in catalogue.projects:
            for comp in project.components:
                source = component_index[comp.key]
                for edge_name, edges in (
                    ("depends_on", comp.depends_on),
                    ("blocked_by", comp.blocked_by),
                    ("emits_events_to", comp.emits_events_to),
                ):
                    for edge in edges:
                        target = component_index[edge.component]
                        desired_edges[(source.id, target.id, edge_name)] = edge

        return desired_edges

    async def _reconcile_edges(
        self,
        session: AsyncSession,
        component_index: dict[str, ComponentRecord],
        catalogue: Catalogue,
        result: CatalogueImportResult,
    ) -> None:
        component_ids = {component.id for component in component_index.values()}
        if not component_ids:
            return

        existing_edges = await self._load_existing_edges(session, component_ids)
        desired_edges = self._build_desired_edges(component_index, catalogue)

        for key, edge in desired_edges.items():
            source_id, target_id, relationship = key
            if key in existing_edges:
                record = existing_edges[key]
                changed = False
                changed |= _set_if_changed(record, "kind", edge.kind)
                changed |= _set_if_changed(record, "rationale", edge.rationale)
                if changed:
                    result.edges_updated += 1
                continue

            session.add(
                ComponentEdgeRecord(
                    from_component_id=source_id,
                    to_component_id=target_id,
                    relationship_type=relationship,
                    kind=edge.kind,
                    rationale=edge.rationale,
                )
            )
            result.edges_created += 1

        for key, record in list(existing_edges.items()):
            if key not in desired_edges:
                await session.delete(record)
                result.edges_deleted += 1


def _session_factory_from_engine(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, expire_on_commit=False)


def build_importer_from_url(
    database_url: str,
    *,
    estate_key: str = "default",
    estate_name: str | None = None,
) -> CatalogueImporter:
    """Construct an importer from a database URL and ensure schema exists."""
    engine = create_async_engine(database_url, future=True)
    asyncio.run(init_catalogue_storage(engine))
    return CatalogueImporter(
        _session_factory_from_engine(engine),
        estate_key=estate_key,
        estate_name=estate_name,
    )


try:  # pragma: no cover - exercised in tests and CLI usage
    _current_broker = dramatiq.get_broker()
except ModuleNotFoundError:
    _current_broker = None

if _current_broker is None:
    dramatiq.set_broker(StubBroker())


@dramatiq.actor
def import_catalogue_job(
    catalogue_path: str,
    database_url: str,
    *,
    commit_sha: str | None = None,
    estate: tuple[str, str | None] | None = None,
) -> None:
    """Dramatiq actor for asynchronous catalogue reconciliation."""
    estate_key, estate_name = estate if estate else ("default", None)
    importer = build_importer_from_url(
        database_url, estate_key=estate_key, estate_name=estate_name
    )
    importer.run_sync(Path(catalogue_path), commit_sha=commit_sha)
