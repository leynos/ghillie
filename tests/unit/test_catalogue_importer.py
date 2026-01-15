"""Unit tests for the catalogue importer and reconciler."""

from __future__ import annotations

import asyncio
import typing as typ
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ghillie.catalogue import (
    CatalogueImporter,
    CatalogueImportRecord,
    CatalogueImportResult,
    CatalogueValidationError,
    Component,
    ComponentEdgeRecord,
    ComponentRecord,
    ProjectRecord,
    Repository,
    RepositoryRecord,
    init_catalogue_storage,
)

EXPECTED_PROJECTS = 2
EXPECTED_COMPONENTS = 7
EXPECTED_REPOS = 6
EXPECTED_EDGES = 6
EXPECTED_IMPORT_RECORDS = 2


@pytest.fixture
def session_factory(tmp_path: Path) -> typ.Iterator[async_sessionmaker[AsyncSession]]:
    """Provide an async session factory bound to a temporary SQLite DB."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'catalogue.db'}")
    asyncio.run(init_catalogue_storage(engine))
    factory = async_sessionmaker(engine, expire_on_commit=False)

    yield factory

    asyncio.run(engine.dispose())


def _count_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[int, int, int, int]:
    async def _inner() -> tuple[int, int, int, int]:
        async with session_factory() as session:
            projects = (await session.scalars(select(ProjectRecord))).all()
            components = (await session.scalars(select(ComponentRecord))).all()
            edges = (await session.scalars(select(ComponentEdgeRecord))).all()
            repos = (await session.scalars(select(RepositoryRecord))).all()
            return len(projects), len(components), len(edges), len(repos)

    return asyncio.run(_inner())


def test_importer_populates_and_idempotent(  # noqa: D103
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    importer = CatalogueImporter(
        session_factory, estate_key="demo", estate_name="Demo Estate"
    )

    first = asyncio.run(
        importer.import_path(
            Path("examples/wildside-catalogue.yaml"), commit_sha="abc123"
        )
    )

    assert first.projects_created == EXPECTED_PROJECTS, (
        "projects_created should match seeded catalogue"
    )
    assert first.components_created == EXPECTED_COMPONENTS, (
        "components_created should match seeded catalogue"
    )
    assert first.repositories_created == EXPECTED_REPOS, (
        "repositories_created should match seeded catalogue"
    )
    assert first.edges_created == EXPECTED_EDGES, (
        "edges_created should match seeded relationships"
    )

    counts_after_first = _count_rows(session_factory)
    assert counts_after_first == (
        EXPECTED_PROJECTS,
        EXPECTED_COMPONENTS,
        EXPECTED_EDGES,
        EXPECTED_REPOS,
    ), (
        "expected counts after first import "
        f"{(EXPECTED_PROJECTS, EXPECTED_COMPONENTS, EXPECTED_EDGES, EXPECTED_REPOS)}, "
        f"got {counts_after_first}"
    )

    second = asyncio.run(
        importer.import_path(
            Path("examples/wildside-catalogue.yaml"), commit_sha="abc123"
        )
    )

    assert second.skipped is True, "duplicate commit should be skipped"
    assert second.projects_created == 0, "no new projects on duplicate commit"
    assert second.components_created == 0, "no new components on duplicate commit"
    assert second.repositories_created == 0, "no new repositories on duplicate commit"
    assert second.edges_created == 0, "no new edges on duplicate commit"

    counts_after_second = _count_rows(session_factory)
    assert counts_after_second == counts_after_first, (
        "counts should remain unchanged after duplicate import"
    )


def test_importer_allows_same_commit_per_estate(  # noqa: D103
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    importer_a = CatalogueImporter(session_factory, estate_key="alpha")
    importer_b = CatalogueImporter(session_factory, estate_key="beta")

    first = asyncio.run(
        importer_a.import_path(
            Path("examples/wildside-catalogue.yaml"), commit_sha="sharedsha"
        )
    )
    second = asyncio.run(
        importer_b.import_path(
            Path("examples/wildside-catalogue.yaml"), commit_sha="sharedsha"
        )
    )

    assert first.skipped is False
    assert second.skipped is False

    async def _count_imports() -> int:
        async with session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(CatalogueImportRecord)
            )
            return int(count or 0)

    count = asyncio.run(_count_imports())
    assert count == EXPECTED_IMPORT_RECORDS


def test_importer_rolls_back_on_invalid_catalogue(  # noqa: D103
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    importer = CatalogueImporter(session_factory, estate_key="demo")
    asyncio.run(
        importer.import_path(
            Path("examples/wildside-catalogue.yaml"), commit_sha="good"
        )
    )
    before = _count_rows(session_factory)

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        """
version: 1
projects:
  - key: bad slug!
    name: Broken
    components: []
""",
        encoding="utf-8",
    )

    with pytest.raises(CatalogueValidationError):
        asyncio.run(importer.import_path(invalid, commit_sha="bad"))

    after = _count_rows(session_factory)
    assert after == before


def test_importer_updates_and_prunes(  # noqa: D103
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    importer = CatalogueImporter(session_factory, estate_key="demo")

    initial = tmp_path / "catalogue-v1.yaml"
    initial.write_text(
        """
version: 1
projects:
  - key: alpha
    name: Alpha
    components:
      - key: alpha-api
        name: Alpha API
        repository:
          owner: org
          name: alpha-api
          default_branch: main
      - key: alpha-worker
        name: Alpha Worker
        repository:
          owner: org
          name: alpha-worker
          default_branch: main
""",
        encoding="utf-8",
    )

    updated = tmp_path / "catalogue-v2.yaml"
    updated.write_text(
        """
version: 1
projects:
  - key: alpha
    name: Alpha v2
    components:
      - key: alpha-api
        name: Alpha API
        repository:
          owner: org
          name: alpha-api
          default_branch: develop
""",
        encoding="utf-8",
    )

    asyncio.run(importer.import_path(initial, commit_sha="v1"))
    first_counts = _count_rows(session_factory)
    assert first_counts == (1, 2, 0, 2)

    result = asyncio.run(importer.import_path(updated, commit_sha="v2"))

    assert result.projects_updated == 1
    assert result.components_deleted == 1
    assert result.repositories_deleted == 1
    assert result.repositories_updated == 1

    final_counts = _count_rows(session_factory)
    assert final_counts == (1, 1, 0, 1)

    async def _check_branch() -> str:
        async with session_factory() as session:
            repo = await session.scalar(select(RepositoryRecord))
            assert repo is not None
            return repo.default_branch

    branch = asyncio.run(_check_branch())
    assert branch == "develop"


def _make_noise_catalogue_yaml(
    enabled: bool,  # noqa: FBT001
    toggles: dict[str, bool],
) -> str:
    """Generate a catalogue YAML with noise configuration."""
    return f"""\
version: 1
projects:
  - key: alpha
    name: Alpha
    noise:
      enabled: {str(enabled).lower()}
      toggles:
        ignore_authors: {str(toggles["ignore_authors"]).lower()}
        ignore_labels: {str(toggles["ignore_labels"]).lower()}
        ignore_paths: {str(toggles["ignore_paths"]).lower()}
        ignore_title_prefixes: {str(toggles["ignore_title_prefixes"]).lower()}
      ignore_authors:
        - dependabot[bot]
      ignore_labels:
        - chore/deps
      ignore_paths:
        - docs/generated/**
      ignore_title_prefixes:
        - "chore:"
    components:
      - key: alpha-api
        name: Alpha API
        repository:
          owner: org
          name: alpha-api
          default_branch: main
"""


async def _load_project_noise(
    session_factory: async_sessionmaker[AsyncSession],
    project_key: str,
) -> dict[str, typ.Any]:
    """Load noise configuration from a project record."""
    async with session_factory() as session:
        project = await session.scalar(
            select(ProjectRecord).where(ProjectRecord.key == project_key)
        )
        assert project is not None
        return project.noise


def _assert_noise_config(
    noise: dict[str, typ.Any],
    *,
    enabled: bool,
    toggles: dict[str, bool],
) -> None:
    """Assert noise configuration matches expected values."""
    assert noise["enabled"] is enabled
    assert noise["toggles"] == toggles
    assert noise["ignore_authors"] == ["dependabot[bot]"]
    assert noise["ignore_labels"] == ["chore/deps"]
    assert noise["ignore_paths"] == ["docs/generated/**"]
    assert noise["ignore_title_prefixes"] == ["chore:"]


def test_importer_persists_noise_configuration(  # noqa: D103
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    # Arrange
    importer = CatalogueImporter(session_factory, estate_key="noise-test")
    toggles_v1 = {
        "ignore_authors": False,
        "ignore_labels": True,
        "ignore_paths": False,
        "ignore_title_prefixes": True,
    }
    toggles_v2 = {
        "ignore_authors": True,
        "ignore_labels": False,
        "ignore_paths": True,
        "ignore_title_prefixes": False,
    }

    first = tmp_path / "catalogue-noise-v1.yaml"
    first.write_text(
        _make_noise_catalogue_yaml(enabled=False, toggles=toggles_v1),
        encoding="utf-8",
    )

    second = tmp_path / "catalogue-noise-v2.yaml"
    second.write_text(
        _make_noise_catalogue_yaml(enabled=True, toggles=toggles_v2),
        encoding="utf-8",
    )

    # Act
    asyncio.run(importer.import_path(first, commit_sha="noise-v1"))

    # Assert
    noise = asyncio.run(_load_project_noise(session_factory, "alpha"))
    _assert_noise_config(noise, enabled=False, toggles=toggles_v1)

    # Act
    asyncio.run(importer.import_path(second, commit_sha="noise-v2"))

    # Assert
    noise_updated = asyncio.run(_load_project_noise(session_factory, "alpha"))
    _assert_noise_config(noise_updated, enabled=True, toggles=toggles_v2)


def test_ensure_repository_normalises_documentation_paths(  # noqa: D103
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    importer = CatalogueImporter(session_factory)

    async def _create_repo(doc_paths: list[str]) -> RepositoryRecord:
        async with session_factory() as session, session.begin():
            repo_index: dict[str, RepositoryRecord] = {}
            component = Component(
                key="alpha-api",
                name="Alpha API",
                repository=Repository(
                    owner="org",
                    name="alpha",
                    documentation_paths=doc_paths,
                ),
            )
            result = CatalogueImportResult("default", None)
            repository = importer._ensure_repository(
                session, repo_index, component, result
            )
            assert repository is not None
            await session.flush()
            return repository

    repository = asyncio.run(
        _create_repo(["docs/roadmap.md", "docs/adr/", "docs/adr/"])
    )
    assert repository.documentation_paths == [
        "docs/roadmap.md",
        "docs/adr/",
    ], "documentation_paths should preserve first-seen order and drop duplicates"


def test_ensure_repository_updates_documentation_paths(  # noqa: D103
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    importer = CatalogueImporter(session_factory)

    async def _create_and_update_repo() -> tuple[
        CatalogueImportResult, CatalogueImportResult, list[str]
    ]:
        async with session_factory() as session, session.begin():
            repo_index: dict[str, RepositoryRecord] = {}
            component = Component(
                key="alpha-api",
                name="Alpha API",
                repository=Repository(
                    owner="org",
                    name="alpha",
                    documentation_paths=["docs/adr/"],
                ),
            )
            first_result = CatalogueImportResult("default", None)
            repository = importer._ensure_repository(
                session, repo_index, component, first_result
            )
            assert repository is not None
            await session.flush()

            assert component.repository is not None
            component.repository.documentation_paths = [
                "docs/roadmap.md",
                "docs/adr/",
            ]
            second_result = CatalogueImportResult("default", None)
            importer._ensure_repository(
                session, repo_index, component, second_result
            )
            await session.flush()

            return first_result, second_result, repository.documentation_paths

    first, second, stored_paths = asyncio.run(_create_and_update_repo())

    assert first.repositories_created == 1
    assert second.repositories_updated == 1
    assert stored_paths == [
        "docs/roadmap.md",
        "docs/adr/",
    ], "documentation_paths should update to the new normalized order"


def test_prune_respects_other_estates(  # noqa: D103
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    importer_a = CatalogueImporter(session_factory, estate_key="alpha")
    importer_b = CatalogueImporter(session_factory, estate_key="beta")

    catalogue_a = tmp_path / "estate-a.yaml"
    catalogue_a.write_text(
        """
version: 1
projects:
  - key: alpha
    name: Alpha
    components:
      - key: alpha-api
        name: Alpha API
        repository:
          owner: org
          name: shared-repo
          default_branch: main
""",
        encoding="utf-8",
    )

    catalogue_b = tmp_path / "estate-b.yaml"
    catalogue_b.write_text(
        """
version: 1
projects:
  - key: beta
    name: Beta
    components:
      - key: beta-api
        name: Beta API
        repository:
          owner: org
          name: shared-repo
          default_branch: main
""",
        encoding="utf-8",
    )

    asyncio.run(importer_a.import_path(catalogue_a, commit_sha="a1"))
    asyncio.run(importer_b.import_path(catalogue_b, commit_sha="b1"))

    catalogue_a_v2 = tmp_path / "estate-a-v2.yaml"
    catalogue_a_v2.write_text(
        """
version: 1
projects:
  - key: alpha
    name: Alpha
    components:
      - key: alpha-api
        name: Alpha API
        lifecycle: planned
""",
        encoding="utf-8",
    )

    asyncio.run(importer_a.import_path(catalogue_a_v2, commit_sha="a2"))

    async def _repo_usage() -> tuple[int, int]:
        async with session_factory() as session:
            repos = (await session.scalars(select(RepositoryRecord))).all()
            components = (
                await session.scalars(
                    select(ComponentRecord).where(
                        ComponentRecord.repository_id.is_not(None)
                    )
                )
            ).all()
            return len(repos), len(components)

    repo_count, component_with_repo = asyncio.run(_repo_usage())
    assert repo_count == 1
    assert component_with_repo == 1
