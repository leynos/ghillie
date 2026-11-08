"""Unit tests for adopting an unowned Silver row during a catalogue sync.

A sync may adopt a Silver row that no estate owns yet. Two syncs can race for
the same row, so these tests cover the claim itself and the policy a losing
sync applies to what it finds afterwards.
"""

from __future__ import annotations

import typing as typ

import pytest

from ghillie.catalogue import CatalogueImporter
from ghillie.registry import RepositoryRegistryService
from ghillie.registry import sync as sync_module
from ghillie.silver.storage import Repository
from tests.fixtures.specs import RepositoryCreateSpec
from tests.unit.registry_service_sync_helpers import fetch_silver_repo

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.fixtures.specs import CreateRepoFn


@pytest.mark.asyncio
async def test_claim_unowned_repository_is_atomic_under_a_stale_view(
    session_factory: async_sessionmaker[AsyncSession],
    create_estates: tuple[str, str],
    create_repo: CreateRepoFn,
) -> None:
    """Only the first claim of an unowned row succeeds; a stale view loses."""
    estate_a_id, estate_b_id = create_estates
    await create_repo("leynos", "adoptme", spec=RepositoryCreateSpec())

    async with session_factory() as stale_session:
        stale_rows = await sync_module._load_silver_repositories(
            stale_session, estate_a_id, ["leynos/adoptme"]
        )
        # End the read transaction but keep the loaded view, which is what a
        # sync that read before the other estate committed would hold.
        await stale_session.commit()
        stale_row = stale_rows["leynos/adoptme"]

    async with session_factory() as winner_session:
        winner_rows = await sync_module._load_silver_repositories(
            winner_session, estate_b_id, ["leynos/adoptme"]
        )
        claimed = await sync_module._claim_unowned_repository(
            winner_session, winner_rows["leynos/adoptme"], estate_b_id
        )
        assert claimed, "The first claim of an unowned row should succeed"
        await winner_session.commit()

    async with session_factory() as loser_session:
        claimed = await sync_module._claim_unowned_repository(
            loser_session, stale_row, estate_a_id
        )
        assert not claimed, "A stale view must not overwrite the winning claim"
        await loser_session.rollback()

    repo = await fetch_silver_repo(session_factory, "leynos", "adoptme")
    assert repo is not None, "The adopted row should still exist"
    assert repo.estate_id == estate_b_id, "The winning estate must keep the row"


@pytest.mark.asyncio
async def test_sync_reports_conflict_when_adoption_loses_a_race(
    session_factory: async_sessionmaker[AsyncSession],
    create_estates: tuple[str, str],
    wildside_catalogue_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sync that loses an adoption race reports a conflict, not a claim."""
    _estate_a_id, estate_b_id = create_estates
    async with session_factory() as session, session.begin():
        session.add(
            Repository(
                github_owner="leynos",
                github_name="wildside",
                default_branch="main",
            )
        )
    importer = CatalogueImporter(
        session_factory, estate_key="estate-a", estate_name="Estate A"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="adoption-race-1")

    original = sync_module._load_silver_repositories

    async def _racing_load(
        session: AsyncSession,
        estate_id: str | None,
        catalogue_slugs: cabc.Iterable[str],
    ) -> dict[str, Repository]:
        """Load in the sync's own session, then let another estate claim it.

        Loading through ``session`` matters: it puts the unowned row in the
        sync's identity map, so the reload after a lost claim has to defeat
        that cached copy to see the winner.
        """
        stale = await original(session, estate_id, catalogue_slugs)
        async with session_factory() as winner_session:
            winner = await original(winner_session, estate_b_id, catalogue_slugs)
            winner["leynos/wildside"].estate_id = estate_b_id
            await winner_session.commit()
        return stale

    monkeypatch.setattr(sync_module, "_load_silver_repositories", _racing_load)

    result = await RepositoryRegistryService(
        session_factory, session_factory
    ).sync_from_catalogue("estate-a")

    assert "leynos/wildside" in result.repositories_conflicted, (
        "A sync that loses the adoption race must report a conflict"
    )
    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None, "The adopted row should still exist"
    assert repo.estate_id == estate_b_id, "The winner's claim must stand"


@pytest.mark.asyncio
async def test_sync_continues_after_losing_a_claim_to_its_own_estate(
    session_factory: async_sessionmaker[AsyncSession],
    create_estates: tuple[str, str],
    wildside_catalogue_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A claim lost to this same estate is not a conflict.

    Two syncs of one estate can read the same unowned row and both try to
    claim it. The loser's view predates the winner's claim, so judging
    ownership from that view would report a conflict against itself. The sync
    must reload the committed row and carry on.
    """
    estate_a_id, _estate_b_id = create_estates
    async with session_factory() as session, session.begin():
        session.add(
            Repository(
                github_owner="leynos",
                github_name="wildside",
                default_branch="main",
            )
        )
    importer = CatalogueImporter(
        session_factory, estate_key="estate-a", estate_name="Estate A"
    )
    await importer.import_path(wildside_catalogue_path, commit_sha="same-estate-race-1")

    original = sync_module._load_silver_repositories

    async def _racing_load(
        session: AsyncSession,
        estate_id: str | None,
        catalogue_slugs: cabc.Iterable[str],
    ) -> dict[str, Repository]:
        """Return the pre-claim view after this estate has claimed the row."""
        async with session_factory() as stale_session:
            stale = await original(stale_session, estate_id, catalogue_slugs)
        async with session_factory() as winner_session:
            winner = await original(winner_session, estate_a_id, catalogue_slugs)
            winner["leynos/wildside"].estate_id = estate_a_id
            await winner_session.commit()
        return stale

    monkeypatch.setattr(sync_module, "_load_silver_repositories", _racing_load)

    result = await RepositoryRegistryService(
        session_factory, session_factory
    ).sync_from_catalogue("estate-a")

    assert "leynos/wildside" not in result.repositories_conflicted, (
        "A claim lost to this same estate must not be reported as a conflict"
    )
    repo = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert repo is not None, "The adopted row should still exist"
    assert repo.estate_id == estate_a_id, "This estate's claim must stand"
    assert repo.catalogue_repository_id is not None, (
        "The sync must still link the row it adopted"
    )
