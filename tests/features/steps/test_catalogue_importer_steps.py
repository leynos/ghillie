"""Behavioural tests for the catalogue importer."""

from __future__ import annotations

import asyncio
import typing as typ
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenario, then, when
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ghillie.catalogue import (
    CatalogueImporter,
    ComponentEdgeRecord,
    ComponentRecord,
    ProjectRecord,
    RepositoryRecord,
    init_catalogue_storage,
)

COMMIT_SHA = "abc123"
EXPECTED_PROJECTS = 2
EXPECTED_COMPONENTS = 7
EXPECTED_REPOS = 6
EXPECTED_EDGES = 6


class ImportContext(typ.TypedDict, total=False):
    """Shared state used by BDD steps."""

    catalogue_path: Path
    importer: CatalogueImporter
    session_factory: async_sessionmaker[AsyncSession]
    first_counts: tuple[int, int, int, int]


@scenario(
    "../catalogue_importer.feature",
    "Importing a catalogue commit populates the estate idempotently",
)
def test_catalogue_importer_bdd() -> None:
    """Behavioural test wrapper for pytest-bdd."""


@pytest.fixture
def import_context(tmp_path: Path) -> typ.Iterator[ImportContext]:
    """Provision a fresh database and importer for each scenario."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bdd-catalogue.db'}")
    asyncio.run(init_catalogue_storage(engine))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    importer = CatalogueImporter(
        session_factory, estate_key="bdd", estate_name="BDD Estate"
    )

    yield {
        "importer": importer,
        "session_factory": session_factory,
    }

    asyncio.run(engine.dispose())


def _counts(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int, int, int]:
    """Return project/component/edge/repository counts from the database."""

    async def _inner() -> tuple[int, int, int, int]:
        async with session_factory() as session:
            projects = (
                await session.scalars(select(ComponentRecord.project_id).distinct())
            ).all()
            components = (await session.scalars(select(ComponentRecord))).all()
            edges = (await session.scalars(select(ComponentEdgeRecord))).all()
            repos = (await session.scalars(select(RepositoryRecord))).all()
            return len(projects), len(components), len(edges), len(repos)

    return asyncio.run(_inner())


@given('the importer uses catalogue at "examples/wildside-catalogue.yaml"')
def bdd_catalogue_path(import_context: ImportContext) -> Path:
    """Persist the path to the example catalogue for later steps."""
    path = Path("examples/wildside-catalogue.yaml")
    assert path.exists(), f"expected example catalogue at {path}"
    import_context["catalogue_path"] = path
    return path


@given("a fresh catalogue database")
def fresh_database(import_context: ImportContext) -> None:
    """Validate the importer fixture was initialised."""
    assert "importer" in import_context, (
        "import_context should contain an importer instance"
    )


@when('the catalogue importer processes commit "abc123"')
def run_import(import_context: ImportContext) -> None:
    """Import the catalogue with the reference commit identifier."""
    assert "catalogue_path" in import_context, "catalogue_path missing from context"
    importer = import_context["importer"]
    asyncio.run(
        importer.import_path(import_context["catalogue_path"], commit_sha=COMMIT_SHA)
    )
    import_context["first_counts"] = _counts(import_context["session_factory"])


@when('the catalogue importer processes commit "abc123" again')
def run_import_again(import_context: ImportContext) -> None:
    """Re-run the import to check idempotency."""
    assert "catalogue_path" in import_context, "catalogue_path missing from context"
    importer = import_context["importer"]
    asyncio.run(
        importer.import_path(import_context["catalogue_path"], commit_sha=COMMIT_SHA)
    )


@then('the repository table contains "leynos/wildside" on branch "main"')
def repository_present(import_context: ImportContext) -> None:
    """Ensure the repository row exists with the expected default branch."""

    async def _assert_repo() -> None:
        async with import_context["session_factory"]() as session:
            repo = await session.scalar(
                select(RepositoryRecord).where(
                    RepositoryRecord.owner == "leynos",
                    RepositoryRecord.name == "wildside",
                )
            )
            assert repo is not None, "expected repository leynos/wildside to exist"
            assert repo.default_branch == "main", (
                "expected default_branch main, got "
                f"{getattr(repo, 'default_branch', None)}"
            )

    asyncio.run(_assert_repo())


@then('the component graph includes "wildside-core" depends_on "wildside-engine"')
def dependency_edge_present(import_context: ImportContext) -> None:
    """Verify the expected component edge is persisted."""

    async def _assert_edge() -> None:
        async with import_context["session_factory"]() as session:
            core = await session.scalar(
                select(ComponentRecord).where(ComponentRecord.key == "wildside-core")
            )
            engine = await session.scalar(
                select(ComponentRecord).where(ComponentRecord.key == "wildside-engine")
            )
            assert core is not None, "expected component wildside-core"
            assert engine is not None, "expected component wildside-engine"
            edge = await session.scalar(
                select(ComponentEdgeRecord).where(
                    ComponentEdgeRecord.from_component_id == core.id,
                    ComponentEdgeRecord.to_component_id == engine.id,
                    ComponentEdgeRecord.relationship_type == "depends_on",
                )
            )
            assert edge is not None, (
                "expected depends_on edge wildside-core -> wildside-engine"
            )

    asyncio.run(_assert_edge())


@then("the catalogue row counts are 2 projects, 7 components, 6 repositories")
def row_counts(import_context: ImportContext) -> None:
    """Confirm expected row counts after initial import."""
    projects, components, edges, repos = _counts(import_context["session_factory"])
    assert projects == EXPECTED_PROJECTS, (
        f"expected {EXPECTED_PROJECTS} projects, got {projects}"
    )
    assert components == EXPECTED_COMPONENTS, (
        f"expected {EXPECTED_COMPONENTS} components, got {components}"
    )
    assert edges == EXPECTED_EDGES, f"expected {EXPECTED_EDGES} edges, got {edges}"
    assert repos == EXPECTED_REPOS, f"expected {EXPECTED_REPOS} repos, got {repos}"


@then("no catalogue rows are duplicated")
def idempotent_counts(import_context: ImportContext) -> None:
    """Validate that the second import leaves counts unchanged."""
    projects, components, edges, repos = _counts(import_context["session_factory"])
    assert "first_counts" in import_context, "first_counts not recorded in context"
    assert (projects, components, edges, repos) == import_context["first_counts"], (
        f"expected idempotent counts {import_context['first_counts']} "
        f"but got {(projects, components, edges, repos)}"
    )


@then('project "wildside" retains catalogue configuration')
def project_configuration_persisted(import_context: ImportContext) -> None:
    """Ensure project-level noise, docs, and status preferences are stored."""

    async def _assert_project() -> None:
        async with import_context["session_factory"]() as session:
            project = await session.scalar(
                select(ProjectRecord).where(ProjectRecord.key == "wildside")
            )

            assert project is not None, "expected project wildside to be imported"
            assert "chore/deps" in project.noise.get("ignore_labels", [])
            assert "docs/roadmap.md" in project.documentation_paths
            assert project.status_preferences.get("summarise_dependency_prs") is False

    asyncio.run(_assert_project())


@then('repository "leynos/wildside" exposes documentation paths')
def repository_documentation_paths(import_context: ImportContext) -> None:
    """Validate repository-level documentation paths are persisted."""

    async def _assert_repo_docs() -> None:
        async with import_context["session_factory"]() as session:
            repository = await session.scalar(
                select(RepositoryRecord).where(
                    RepositoryRecord.owner == "leynos",
                    RepositoryRecord.name == "wildside",
                )
            )

            assert repository is not None, "expected repository leynos/wildside"
            assert repository.documentation_paths == ["docs/adr/", "docs/roadmap.md"]

    asyncio.run(_assert_repo_docs())


@then(parsers.parse('repository "{owner}/{name}" has no documentation paths'))
def repository_without_documentation_paths(
    import_context: ImportContext, owner: str, name: str
) -> None:
    """Validate repositories without documentation config default to empty paths."""

    async def _assert_repo_no_docs() -> None:
        async with import_context["session_factory"]() as session:
            repository = await session.scalar(
                select(RepositoryRecord).where(
                    RepositoryRecord.owner == owner,
                    RepositoryRecord.name == name,
                )
            )

            assert repository is not None, f"expected repository {owner}/{name}"
            assert repository.documentation_paths == []

    asyncio.run(_assert_repo_no_docs())
