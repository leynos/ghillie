"""Concurrency tests for RepositoryRegistryService catalogue syncing.

These tests drive two overlapping write transactions. They need a backend with
multi-version concurrency control, so they skip unless the session factory is
bound to Postgres.
"""

from __future__ import annotations

import asyncio
import typing as typ

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ghillie.catalogue import (
    CatalogueImporter,
    ComponentRecord,
    Estate,
    ProjectRecord,
    RepositoryRecord,
)
from ghillie.common.slug import repo_slug
from ghillie.registry import RegistrySyncError, RepositoryRegistryService
from ghillie.registry import sync as sync_module
from ghillie.silver.storage import Repository
from tests.unit.registry_service_sync_helpers import fetch_silver_repo

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.registry import SyncResult


def _require_overlapping_transactions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Skip unless the backend can run two write transactions at once.

    SQLite serialises writers, so the interleaving these tests need surfaces as
    a lock error rather than the constraint violation a Postgres deployment
    sees. The suite prefers py-pglite Postgres and falls back to SQLite.
    """
    bind = session_factory.kw.get("bind")
    dialect = getattr(bind, "dialect", None)
    if dialect is None or dialect.name != "postgresql":
        pytest.skip("overlapping write transactions need Postgres MVCC")


async def _import_for_estate(
    session_factory: async_sessionmaker[AsyncSession],
    catalogue_path: Path,
    estate_key: str,
    commit_sha: str,
) -> None:
    """Import the catalogue for one estate.

    Imports run one at a time: the catalogue tables are global, so only the
    sync that follows is meant to overlap. The display name is derived from the
    key, which is how the fixtures name these estates.
    """
    importer = CatalogueImporter(
        session_factory,
        estate_key=estate_key,
        estate_name=estate_key.replace("-", " ").title(),
    )
    await importer.import_path(catalogue_path, commit_sha=commit_sha)


def _synchronise_silver_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make both syncs finish their Silver read before either writes.

    Real concurrent syncs interleave unpredictably. A barrier forces the one
    interleaving that matters here: both loads run first, so neither sync can
    see what the other is about to write.
    """
    original = sync_module._load_silver_repositories
    both_loaded = asyncio.Barrier(2)

    async def _load_then_wait(
        session: AsyncSession,
        estate_id: str | None,
        catalogue_slugs: cabc.Iterable[str],
    ) -> dict[str, Repository]:
        rows = await original(session, estate_id, catalogue_slugs)
        await both_loaded.wait()
        return rows

    monkeypatch.setattr(sync_module, "_load_silver_repositories", _load_then_wait)


async def _catalogue_repository_ids(
    session_factory: async_sessionmaker[AsyncSession],
    estate_key: str,
) -> dict[str, str]:
    """Return slug -> catalogue repository id for one estate's catalogue."""
    async with session_factory() as session:
        rows = await session.execute(
            select(RepositoryRecord.id, RepositoryRecord.owner, RepositoryRecord.name)
            .join(
                ComponentRecord,
                ComponentRecord.repository_id == RepositoryRecord.id,
            )
            .join(ProjectRecord, ProjectRecord.id == ComponentRecord.project_id)
            .join(Estate, Estate.id == ProjectRecord.estate_id)
            .where(Estate.key == estate_key)
        )
        return {repo_slug(owner, name): repo_id for repo_id, owner, name in rows}


async def _seed_estate_naming(
    session_factory: async_sessionmaker[AsyncSession],
    estate_id: str,
    owner: str,
    name: str,
) -> str:
    """Give one estate a catalogue that names a single repository.

    Returns the catalogue repository id, so the caller can link an unowned
    Silver row to it and put that row in the other estate's removal path.
    """
    async with session_factory() as session, session.begin():
        project = ProjectRecord(
            estate_id=estate_id,
            key=f"{owner}-{name}",
            name=f"{owner}/{name}",
        )
        repository = RepositoryRecord(
            owner=owner,
            name=name,
            default_branch="main",
        )
        session.add_all([project, repository])
        await session.flush()
        session.add(
            ComponentRecord(
                project_id=project.id,
                repository_id=repository.id,
                key="component",
                name="Component",
                type="service",
                lifecycle="active",
            )
        )
        await session.flush()
        return repository.id


async def _run_two_syncs(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[SyncResult | BaseException]:
    """Sync estate-a and estate-b at the same time and collect both outcomes."""

    async def _sync(estate_key: str) -> SyncResult:
        service = RepositoryRegistryService(session_factory, session_factory)
        return await service.sync_from_catalogue(estate_key)

    gathered = await asyncio.wait_for(
        asyncio.gather(
            _sync("estate-a"),
            _sync("estate-b"),
            return_exceptions=True,
        ),
        timeout=60,
    )
    return list(gathered)


def _completed(results: list[SyncResult | BaseException]) -> list[SyncResult]:
    """Return the successful results, failing when a sync aborted."""
    failures = [result for result in results if isinstance(result, BaseException)]
    assert not failures, f"Neither overlapping sync should abort: {failures!r}"
    return [typ.cast("SyncResult", result) for result in results]


@pytest.mark.asyncio
async def test_overlapping_syncs_adopt_an_unowned_row_once(
    session_factory: async_sessionmaker[AsyncSession],
    create_estates: tuple[str, str],
    wildside_catalogue_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two estates racing to adopt one unowned row leave it with one owner."""
    estate_a_id, estate_b_id = create_estates
    _require_overlapping_transactions(session_factory)
    async with session_factory() as session, session.begin():
        session.add(
            Repository(
                github_owner="leynos",
                github_name="wildside",
                default_branch="main",
            )
        )
    await _import_for_estate(
        session_factory, wildside_catalogue_path, "estate-a", "adopt-a"
    )
    await _import_for_estate(
        session_factory, wildside_catalogue_path, "estate-b", "adopt-b"
    )
    _synchronise_silver_load(monkeypatch)

    catalogue_ids = {
        "estate-a": await _catalogue_repository_ids(session_factory, "estate-a"),
        "estate-b": await _catalogue_repository_ids(session_factory, "estate-b"),
    }
    completed = _completed(await _run_two_syncs(session_factory))

    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None, "The adopted row should still exist"
    assert repo.estate_id in {estate_a_id, estate_b_id}, (
        "Exactly one estate must own the adopted row"
    )
    winner_index = 0 if repo.estate_id == estate_a_id else 1
    winner_key = "estate-a" if winner_index == 0 else "estate-b"
    assert "leynos/wildside" not in completed[winner_index].repositories_conflicted, (
        "The estate that won the adoption must not report a conflict"
    )
    assert "leynos/wildside" in completed[1 - winner_index].repositories_conflicted, (
        "The estate that lost the adoption must report the conflict"
    )
    # Both estates import the same catalogue file, and catalogue repositories
    # are unique per owner/name, so the two estates share one catalogue id and
    # it cannot distinguish winner from loser. The row's estate is the field
    # the losing sync would have overwritten.
    assert (
        repo.catalogue_repository_id == catalogue_ids[winner_key]["leynos/wildside"]
    ), "The winner's catalogue link must survive the losing sync"
    async with session_factory() as session:
        rows = await session.scalars(
            select(Repository).where(
                Repository.github_owner == "leynos",
                Repository.github_name == "wildside",
            )
        )
        assert len(rows.all()) == 1, "The race must leave exactly one Silver row"


@pytest.mark.asyncio
async def test_overlapping_syncs_across_both_phases_do_not_deadlock(
    session_factory: async_sessionmaker[AsyncSession],
    create_estates: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claiming one row while removing the other cannot deadlock.

    Each estate names one of two unowned, catalogue-linked rows, so each claims
    its own row and removes the other's. Ordering only the catalogue phase
    would leave the two estates taking those four locks in opposite orders, and
    Postgres would abort one of them.
    """
    estate_a_id, estate_b_id = create_estates
    _require_overlapping_transactions(session_factory)
    alpha_id = await _seed_estate_naming(
        session_factory, estate_a_id, "leynos", "alpha"
    )
    beta_id = await _seed_estate_naming(session_factory, estate_b_id, "leynos", "beta")
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                Repository(
                    github_owner="leynos",
                    github_name="alpha",
                    default_branch="main",
                    catalogue_repository_id=alpha_id,
                    ingestion_enabled=True,
                ),
                Repository(
                    github_owner="leynos",
                    github_name="beta",
                    default_branch="main",
                    catalogue_repository_id=beta_id,
                    ingestion_enabled=True,
                ),
            ]
        )
    _synchronise_silver_load(monkeypatch)

    completed = _completed(await _run_two_syncs(session_factory))

    assert len(completed) == 2, "Both overlapping syncs must finish"
    alpha = await fetch_silver_repo(session_factory, "leynos", "alpha")
    beta = await fetch_silver_repo(session_factory, "leynos", "beta")
    assert alpha is not None, "The alpha row must still exist"
    assert beta is not None, "The beta row must still exist"
    assert alpha.estate_id == estate_a_id, "Estate A must keep the row it names"
    assert beta.estate_id == estate_b_id, "Estate B must keep the row it names"


@pytest.mark.asyncio
async def test_overlapping_syncs_insert_each_slug_once(
    session_factory: async_sessionmaker[AsyncSession],
    create_estates: tuple[str, str],
    wildside_catalogue_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two syncs racing to insert the same slugs create six rows, not twelve."""
    estate_a_id, estate_b_id = create_estates
    _require_overlapping_transactions(session_factory)
    await _import_for_estate(
        session_factory, wildside_catalogue_path, "estate-a", "race-a"
    )
    await _import_for_estate(
        session_factory, wildside_catalogue_path, "estate-b", "race-b"
    )
    _synchronise_silver_load(monkeypatch)

    completed = _completed(await _run_two_syncs(session_factory))

    assert sum(result.repositories_created for result in completed) == 6, (
        "Each of the six catalogue slugs must be inserted exactly once"
    )
    assert sum(len(result.repositories_conflicted) for result in completed) == 6, (
        "Every slug lost to the other estate must be reported once"
    )
    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None, "The raced repository should exist"
    assert repo.estate_id in {estate_a_id, estate_b_id}, (
        "The surviving row must belong to exactly one estate"
    )


@pytest.mark.asyncio
async def test_lost_insert_reports_a_conflict_instead_of_aborting(
    session_factory: async_sessionmaker[AsyncSession],
    create_estates: tuple[str, str],
    wildside_catalogue_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sync whose read missed another estate's row reports it, not aborts."""
    _estate_a_id, estate_b_id = create_estates
    async with session_factory() as session, session.begin():
        session.add(
            Repository(
                github_owner="leynos",
                github_name="wildside",
                default_branch="main",
                estate_id=estate_b_id,
            )
        )
    await _import_for_estate(
        session_factory, wildside_catalogue_path, "estate-a", "lost-insert"
    )

    async def _empty_load(*_args: object, **_kwargs: object) -> dict[str, Repository]:
        """Simulate a sync whose read missed a row another sync inserted."""
        return {}

    monkeypatch.setattr(sync_module, "_load_silver_repositories", _empty_load)

    result = await RepositoryRegistryService(
        session_factory, session_factory
    ).sync_from_catalogue("estate-a")

    assert "leynos/wildside" in result.repositories_conflicted, (
        "A lost insert must be reported as a conflict, not abort the estate sync"
    )
    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None, "The winning row should still exist"
    assert repo.estate_id == estate_b_id, "The winning estate must keep the row"


@pytest.mark.asyncio
async def test_insert_failure_without_a_surviving_row_still_aborts(
    session_factory: async_sessionmaker[AsyncSession],
    create_estates: tuple[str, str],
    wildside_catalogue_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An integrity failure that no racing insert explains is not swallowed."""
    _estate_a_id, estate_b_id = create_estates
    async with session_factory() as session, session.begin():
        # Owned by the other estate so the syncing estate never loads it; the
        # collision must come from the primary key alone.
        placeholder = Repository(
            github_owner="leynos",
            github_name="placeholder",
            default_branch="main",
            estate_id=estate_b_id,
        )
        session.add(placeholder)
        await session.flush()
        placeholder_id = placeholder.id
    await _import_for_estate(
        session_factory,
        wildside_catalogue_path,
        "estate-a",
        "unexplained-integrity",
    )

    original_create = sync_module._create_silver_repository

    def _colliding_create(
        cat_repo: RepositoryRecord,
        context: object,
        decision: object,
    ) -> Repository:
        """Create the row with a primary key an unrelated row already uses."""
        created = original_create(
            cat_repo,
            typ.cast("typ.Any", context),
            typ.cast("typ.Any", decision),
        )
        created.id = placeholder_id
        return created

    monkeypatch.setattr(sync_module, "_create_silver_repository", _colliding_create)

    with pytest.raises(RegistrySyncError) as excinfo:
        await RepositoryRegistryService(
            session_factory, session_factory
        ).sync_from_catalogue("estate-a")

    assert isinstance(excinfo.value.__cause__, IntegrityError), (
        "An integrity failure with no surviving row must keep its cause so the "
        "API can still answer 409"
    )
