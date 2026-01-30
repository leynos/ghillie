"""Catalogue importer and reconciler.

Usage
-----
Import a catalogue file asynchronously::

    from pathlib import Path
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from ghillie.catalogue import CatalogueImporter, init_catalogue_storage

    engine = create_async_engine("sqlite+aiosqlite:///catalogue.db")
    await init_catalogue_storage(engine)
    importer = CatalogueImporter(async_sessionmaker(engine, expire_on_commit=False))
    await importer.import_path(
        Path("examples/wildside-catalogue.yaml"), commit_sha="abc123"
    )

Run the same import synchronously (CLI / worker startup)::

    importer.run_sync(Path("examples/wildside-catalogue.yaml"), commit_sha="abc123")

The importer:

    * wraps each reconciliation in a **single transaction** to avoid partial writes;
    * is **idempotent per estate + commit_sha**; repeated imports of the same
      commit for the same estate are skipped; and
    * prunes components and edges only within the current estate, and prunes
      repositories only when they are unused across *all* estates.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
import typing as typ
from pathlib import Path

import dramatiq
import msgspec
from dramatiq.brokers.stub import StubBroker
from sqlalchemy import func, select
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
    import collections.abc as cabc

    from .models import Catalogue, Component, ComponentLink

SessionFactory = async_sessionmaker[AsyncSession]


@dataclasses.dataclass(slots=True)
class CatalogueImportResult:
    """Summary of a catalogue reconciliation run.

    Parameters
    ----------
    estate_key:
        Slug of the estate processed.
    commit_sha:
        Commit SHA used to identify this import attempt.
    projects_created/updated/deleted, components_created/updated/deleted,
    repositories_created/updated/deleted, edges_created/updated/deleted:
        Counters describing reconciliation effects.
    skipped:
        True when the commit was already processed for this estate and work was
        short-circuited.

    """

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
    """Update an attribute when the incoming value differs."""
    current = getattr(model, attr)
    if current == value:
        return False
    setattr(model, attr, value)
    return True


class CatalogueImporter:
    """Import catalogue files into the persistence layer.

    Parameters
    ----------
    session_factory:
        Async session factory (or zero-arg callable returning one) bound to the
        target database.
    estate_key:
        Slug for the estate being reconciled.
    estate_name:
        Optional display name for the estate.

    Notes
    -----
    Each call to :meth:`import_catalogue` or :meth:`import_path` runs inside a
    single transaction, is idempotent per estate+commit, and prunes only records
    no longer referenced within the same estate.

    """

    def __init__(
        self,
        session_factory: SessionFactory | cabc.Callable[[], AsyncSession],
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
        """Load and import a catalogue file from disk.

        Parameters
        ----------
        catalogue_path:
            Path to the YAML catalogue.
        commit_sha:
            Optional commit SHA for idempotency tracking.

        Returns
        -------
        CatalogueImportResult
            Summary of the reconciliation run.

        """
        catalogue = load_catalogue(catalogue_path)
        return await self.import_catalogue(catalogue, commit_sha=commit_sha)

    async def import_catalogue(
        self, catalogue: Catalogue, *, commit_sha: str | None = None
    ) -> CatalogueImportResult:
        """Validate and reconcile an in-memory catalogue instance.

        Parameters
        ----------
        catalogue:
            Parsed catalogue instance.
        commit_sha:
            Optional commit SHA for idempotency tracking.

        Returns
        -------
        CatalogueImportResult
            Summary of reconciliation effects.

        Raises
        ------
        CatalogueValidationError
            If the catalogue is structurally invalid.

        """
        result = CatalogueImportResult(self.estate_key, commit_sha)

        # Defensive: callers passing in-memory catalogues may bypass loader
        # validation; enforce structural checks here to guarantee global
        # component-key uniqueness across the estate and valid edges.
        from .validation import validate_catalogue  # local import to avoid cycles

        validate_catalogue(catalogue)

        async with self._session_factory() as session, session.begin():
            estate = await self._ensure_estate(session)
            existing_import = None
            if commit_sha:
                existing_import = await session.scalar(
                    select(CatalogueImportRecord).where(
                        CatalogueImportRecord.commit_sha == commit_sha,
                        CatalogueImportRecord.estate_id == estate.id,
                    )
                )
                if existing_import:
                    result.skipped = True
                    return result

            project_index = await self._reconcile_projects(
                session, estate, catalogue, result
            )
            component_index = await self._reconcile_components(
                session, project_index, estate.id, catalogue, result
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
        """Run the importer synchronously for blocking contexts.

        Parameters
        ----------
        catalogue_path:
            Path to the YAML catalogue to import.
        commit_sha:
            Optional commit SHA to record for idempotency tracking.

        Returns
        -------
        CatalogueImportResult
            Summary of reconciliation effects.

        Notes
        -----
        This helper wraps :meth:`import_path` with ``asyncio.run`` and must be
        called only from synchronous code paths where no event loop is running
        (for example, CLI entrypoints or Dramatiq actors).

        """
        return asyncio.run(self.import_path(catalogue_path, commit_sha=commit_sha))

    async def _ensure_estate(self, session: AsyncSession) -> Estate:
        """Upsert the estate record and return the managed instance."""
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
        """Upsert and prune project records for the given estate."""
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
                    record, "noise", msgspec.to_builtins(project.noise)
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
                    noise=msgspec.to_builtins(project.noise),
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

    async def _reconcile_components(  # noqa: PLR0913
        self,
        session: AsyncSession,
        project_index: dict[str, ProjectRecord],
        estate_id: str,
        catalogue: Catalogue,
        result: CatalogueImportResult,
    ) -> dict[str, ComponentRecord]:
        """Upsert components per project and prune missing ones, then prune repos."""
        # Catalogue validation enforces global component key uniqueness across
        # an estate. Component indexing here depends on that invariant.
        repo_index = {
            repo.slug: repo
            for repo in (await session.scalars(select(RepositoryRecord))).all()
        }
        existing_repo_ids = {repo.id for repo in repo_index.values()}

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
                        "repository",
                        repository_record,
                    )
                    if changed:
                        result.components_updated += 1
                else:
                    comp_record = ComponentRecord(
                        project_id=record.id,
                        repository=repository_record,
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
            estate_id,
            existing_repo_ids,
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
        """Upsert a repository for the component; return None when absent."""
        if component.repository is None:
            return None

        slug = component.repository.slug
        documentation_paths = list(
            dict.fromkeys(component.repository.documentation_paths)
        )
        repository = repo_index.get(slug)
        if repository is None:
            repository = RepositoryRecord(
                owner=component.repository.owner,
                name=component.repository.name,
                default_branch=component.repository.default_branch,
                documentation_paths=documentation_paths,
            )
            session.add(repository)
            repo_index[slug] = repository
            result.repositories_created += 1
            return repository

        changed = False
        changed |= _set_if_changed(
            repository, "default_branch", component.repository.default_branch
        )
        changed |= _set_if_changed(
            repository, "documentation_paths", documentation_paths
        )
        if changed:
            result.repositories_updated += 1
        return repository

    async def _prune_unreferenced_repositories(  # noqa: PLR0913
        self,
        session: AsyncSession,
        repo_index: dict[str, RepositoryRecord],
        component_index: dict[str, ComponentRecord],
        estate_id: str,
        existing_repo_ids: set[str],
        result: CatalogueImportResult,
    ) -> None:
        """Delete repositories unreferenced by any component across estates."""
        desired_repo_ids: set[str] = set()
        for comp in component_index.values():
            repo = comp.repository
            repo_id = getattr(repo, "id", None)
            if repo_id is not None:
                desired_repo_ids.add(repo_id)
        for slug, repository in list(repo_index.items()):
            if (
                repository.id in existing_repo_ids
                and repository.id not in desired_repo_ids
            ):
                other_usage = await session.scalar(
                    select(func.count())
                    .select_from(ComponentRecord)
                    .join(ProjectRecord, ComponentRecord.project_id == ProjectRecord.id)
                    .where(
                        ComponentRecord.repository_id == repository.id,
                        ProjectRecord.estate_id != estate_id,
                    )
                )
                if other_usage and other_usage > 0:
                    continue
                await session.delete(repository)
                result.repositories_deleted += 1
                repo_index.pop(slug, None)

    async def _load_existing_edges(
        self,
        session: AsyncSession,
        component_ids: set[str],
    ) -> dict[tuple[str, str, str], ComponentEdgeRecord]:
        """Load existing edges originating from the provided component IDs."""
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
        """Build desired edge set from the catalogue, raising on unknown targets."""
        # Edge resolution assumes component keys are globally unique within an
        # estate and present in ``component_index``.
        from .validation import CatalogueValidationError

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
                        try:
                            target = component_index[edge.component]
                        except KeyError as exc:
                            message = (
                                f"edge from {comp.key} references unknown component "
                                f"{edge.component}; catalogue must maintain globally "
                                "unique component keys"
                            )
                            raise CatalogueValidationError([message]) from exc
                        desired_edges[(source.id, target.id, edge_name)] = edge

        return desired_edges

    async def _reconcile_edges(
        self,
        session: AsyncSession,
        component_index: dict[str, ComponentRecord],
        catalogue: Catalogue,
        result: CatalogueImportResult,
    ) -> None:
        """Upsert and prune component edges for the current estate."""
        await session.flush()
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
    """Create an async session factory with expire_on_commit disabled."""
    return async_sessionmaker(engine, expire_on_commit=False)


def build_importer_from_url(
    database_url: str,
    *,
    estate_key: str = "default",
    estate_name: str | None = None,
) -> CatalogueImporter:
    """Construct an importer from a database URL in synchronous contexts.

    Parameters
    ----------
    database_url:
        SQLAlchemy URL for the catalogue database.
    estate_key:
        Slug identifying the estate to reconcile.
    estate_name:
        Human-friendly estate name; defaults to ``estate_key`` when omitted.

    Returns
    -------
    CatalogueImporter
        An importer bound to a session factory for the given database.

    Notes
    -----
    This helper calls ``asyncio.run`` to initialise the schema and should only
    be used from synchronous startup or worker bootstrap code where no event
    loop is running. In asynchronous contexts, construct an ``AsyncEngine``,
    ``await init_catalogue_storage(engine)``, and pass an ``async_sessionmaker``
    into :class:`CatalogueImporter` directly.

    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:  # pragma: no cover - sanity guard
        message = (
            "build_importer_from_url must be called from sync code; use an "
            "AsyncEngine + init_catalogue_storage + CatalogueImporter in async contexts"
        )
        raise RuntimeError(message)

    engine = create_async_engine(database_url, future=True)
    asyncio.run(init_catalogue_storage(engine))
    return CatalogueImporter(
        _session_factory_from_engine(engine),
        estate_key=estate_key,
        estate_name=estate_name,
    )


_IMPORTER_CACHE: dict[tuple[str, str, str | None], CatalogueImporter] = {}


try:  # pragma: no cover - exercised in tests and CLI usage
    _current_broker = dramatiq.get_broker()
except ModuleNotFoundError:
    _current_broker = None

if _current_broker is None:
    allow_stub = os.environ.get("GHILLIE_ALLOW_STUB_BROKER", "")
    running_tests = "pytest" in sys.modules or any(
        key in os.environ
        for key in ["PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS"]
    )
    if allow_stub.lower() in {"1", "true", "yes"} or running_tests:
        dramatiq.set_broker(StubBroker())
    else:  # pragma: no cover - guard for prod misconfigurations
        message = (
            "No Dramatiq broker configured. Set GHILLIE_ALLOW_STUB_BROKER=1 for "
            "local/test runs or configure a real broker."
        )
        raise RuntimeError(message)


@dramatiq.actor
def import_catalogue_job(
    catalogue_path: str,
    database_url: str,
    *,
    commit_sha: str | None = None,
    estate: tuple[str, str | None] | None = None,
) -> None:
    """Dramatiq actor for asynchronous catalogue reconciliation.

    Parameters
    ----------
    catalogue_path:
        Absolute path to the catalogue file to import.
    database_url:
        SQLAlchemy URL for the catalogue database.
    commit_sha:
        Optional commit SHA used for idempotency.
    estate:
        Tuple of (estate_key, estate_name) to scope the import.

    Notes
    -----
    Intended for use by background workers; delegates to
    :func:`build_importer_from_url` which must run in synchronous contexts.

    """
    estate_key, estate_name = estate if estate else ("default", None)
    cache_key = (database_url, estate_key, estate_name)
    importer = _IMPORTER_CACHE.get(cache_key)
    if importer is None:
        importer = build_importer_from_url(
            database_url, estate_key=estate_key, estate_name=estate_name
        )
        _IMPORTER_CACHE[cache_key] = importer
    importer.run_sync(Path(catalogue_path), commit_sha=commit_sha)
