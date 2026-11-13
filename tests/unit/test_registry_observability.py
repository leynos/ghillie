"""Unit tests for the events a registry sync emits.

The events are asserted through the house femtologging capture helper, so the
tests pin the text an operator would actually read rather than a mock call.
"""

from __future__ import annotations

import contextlib
import typing as typ

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from ghillie.catalogue import CatalogueImporter
from ghillie.catalogue.storage import RepositoryRecord
from ghillie.registry import SyncResult
from ghillie.registry import sync as sync_module
from ghillie.registry.errors import RegistrySyncError
from ghillie.registry.observability import SyncEventBuffer
from ghillie.registry.storage import DialectUpsertStrategy, claim_unowned_repository
from ghillie.silver.storage import Repository
from tests.fixtures.specs import RepositoryCreateSpec
from tests.helpers.femtologging_capture import FemtoLogCapture, capture_femto_logs
from tests.unit.registry_service_sync_helpers import (
    catalogue_naming,
    fetch_silver_repo,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.registry.storage import UpsertStrategy
    from tests.fixtures.specs import CreateRepoFn

_LOGGER_NAME = "ghillie.registry.observability"

_DRIVER_TEXT = "connection lost to the Silver database"


class _FailingSession:
    """A session whose transaction cannot start, as a lost connection would be."""

    async def begin(self) -> typ.NoReturn:
        """Raise the driver error the sync must translate and sanitise."""
        raise SQLAlchemyError(_DRIVER_TEXT)


@contextlib.asynccontextmanager
async def _failing_silver_factory() -> cabc.AsyncIterator[_FailingSession]:
    """Yield a session that cannot begin, letting the sync see a driver error."""
    yield _FailingSession()


class _ExplodingStrategy:
    """An upsert strategy that fails as a driver would while building an insert."""

    def build(self, session: AsyncSession, row: Repository) -> typ.NoReturn:
        """Raise instead of building, so the sync meets a database failure."""
        raise SQLAlchemyError(_DRIVER_TEXT)


async def _import_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
    catalogue_path: Path,
    *,
    commit_sha: str,
    names: tuple[str, ...] = ("wildside",),
) -> None:
    """Import a catalogue naming the repositories these tests use."""
    catalogue_path.write_text(catalogue_naming(names), encoding="utf-8")
    importer = CatalogueImporter(session_factory, estate_key="test")
    await importer.import_path(catalogue_path, commit_sha=commit_sha)


async def _catalogue_repository(
    session_factory: async_sessionmaker[AsyncSession],
    name: str,
) -> RepositoryRecord:
    """Load the catalogue record for one repository these tests name."""
    async with session_factory() as session:
        record = await session.scalar(
            select(RepositoryRecord).where(
                RepositoryRecord.owner == "leynos",
                RepositoryRecord.name == name,
            )
        )
    assert record is not None, f"The catalogue should define leynos/{name}"
    return record


def _messages(capture: FemtoLogCapture) -> list[str]:
    """Return the captured messages in arrival order."""
    return [record.message for record in capture.records]


@pytest.mark.asyncio
async def test_a_successful_sync_logs_one_completion_event(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A sync that persists its work logs one completion line with the counts."""
    catalogue = tmp_path / "catalogue.yaml"
    await _import_catalogue(
        session_factory, catalogue, commit_sha="observability-success"
    )

    with capture_femto_logs(_LOGGER_NAME) as capture:
        result = await sync_module.sync_from_catalogue(
            session_factory, session_factory, "test"
        )
        capture.wait_for_count(1)

    assert result.repositories_created == 1, "The sync should create one row"
    messages = _messages(capture)
    assert len(messages) == 1, "A successful sync should log exactly one event"
    assert capture.records[0].level == "INFO", "Completion is an informational event"
    message = messages[0]
    assert "[SYNC_COMPLETED]" in message
    assert "estate_key=test" in message
    assert "dry_run=false" in message
    assert "outcome=success" in message
    assert "repositories_created=1" in message
    assert "repositories_updated=0" in message
    assert "repositories_deactivated=0" in message
    assert "repositories_conflicted=0" in message
    assert "repositories_left_disabled=0" in message
    assert "duration_seconds=" in message


@pytest.mark.asyncio
async def test_a_dry_run_reports_itself_as_a_dry_run(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """The completion event says whether the run rolled its work back."""
    catalogue = tmp_path / "catalogue.yaml"
    await _import_catalogue(
        session_factory, catalogue, commit_sha="observability-dry-run"
    )

    with capture_femto_logs(_LOGGER_NAME) as capture:
        await sync_module.sync_from_catalogue(
            session_factory,
            session_factory,
            "test",
            options=sync_module.SyncOptions(dry_run=True),
        )
        capture.wait_for_count(1)

    message = _messages(capture)[0]
    assert "[SYNC_COMPLETED]" in message
    assert "dry_run=true" in message


@pytest.mark.asyncio
async def test_a_failed_sync_logs_the_reason_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A failed sync logs one error line carrying the sanitised reason."""
    with (
        capture_femto_logs(_LOGGER_NAME) as capture,
        pytest.raises(RegistrySyncError),
    ):
        await sync_module.sync_from_catalogue(
            session_factory, session_factory, "nonexistent-estate"
        )
    capture.wait_for_count(1)

    messages = _messages(capture)
    assert len(messages) == 1, "A failed sync should log exactly one event"
    assert capture.records[0].level == "ERROR", "Failure is an error-level event"
    message = messages[0]
    assert "[SYNC_FAILED]" in message
    assert "estate_key=nonexistent-estate" in message
    assert "dry_run=false" in message
    assert "outcome=failure" in message
    assert "reason=Estate not found" in message


@pytest.mark.asyncio
async def test_a_database_failure_logs_the_sanitized_reason(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A driver failure logs one error line whose reason carries no driver text."""
    catalogue = tmp_path / "catalogue.yaml"
    await _import_catalogue(
        session_factory, catalogue, commit_sha="observability-database-failure"
    )
    failing_factory = typ.cast(
        "async_sessionmaker[AsyncSession]", _failing_silver_factory
    )

    with (
        capture_femto_logs(_LOGGER_NAME) as capture,
        pytest.raises(RegistrySyncError),
    ):
        await sync_module.sync_from_catalogue(session_factory, failing_factory, "test")
    capture.wait_for_count(1)

    messages = _messages(capture)
    assert len(messages) == 1, "A failed sync should log exactly one event"
    assert capture.records[0].level == "ERROR", "Failure is an error-level event"
    assert "[SYNC_FAILED]" in messages[0]
    assert "reason=Database error during sync" in messages[0]
    assert _DRIVER_TEXT not in messages[0], (
        "The failure event must carry the sanitised reason, not driver text"
    )


@pytest.mark.asyncio
async def test_a_conflict_logs_the_slug_and_counts_it(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A repository another estate owns is logged as a conflict and counted."""
    catalogue = tmp_path / "catalogue.yaml"
    await _import_catalogue(
        session_factory, catalogue, commit_sha="observability-conflict"
    )
    async with session_factory() as session, session.begin():
        session.add(
            Repository(
                github_owner="leynos",
                github_name="wildside",
                default_branch="main",
                estate_id="other-estate",
                ingestion_enabled=True,
                documentation_paths=[],
            )
        )

    with capture_femto_logs(_LOGGER_NAME) as capture:
        result = await sync_module.sync_from_catalogue(
            session_factory, session_factory, "test"
        )
        capture.wait_for_count(2)

    assert result.repositories_conflicted == ["leynos/wildside"], (
        "The other estate's row should be reported as a conflict"
    )
    messages = _messages(capture)
    conflicts = [message for message in messages if "[SYNC_CONFLICTED]" in message]
    assert len(conflicts) == 1, "Each conflict should be logged once"
    assert "estate_key=test" in conflicts[0]
    assert "slug=leynos/wildside" in conflicts[0]
    completed = [message for message in messages if "[SYNC_COMPLETED]" in message]
    assert len(completed) == 1, "The run should still log its completion"
    assert "repositories_conflicted=1" in completed[0]


@pytest.mark.asyncio
async def test_an_ingestion_toggle_change_logs_the_transition(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Changing a row's ingestion flag logs the transition and the new state."""
    catalogue = tmp_path / "catalogue.yaml"
    await _import_catalogue(
        session_factory, catalogue, commit_sha="observability-transition"
    )
    await sync_module.sync_from_catalogue(session_factory, session_factory, "test")

    async with session_factory() as session, session.begin():
        catalogue_repository = await session.scalar(
            select(RepositoryRecord).where(
                RepositoryRecord.owner == "leynos",
                RepositoryRecord.name == "wildside",
            )
        )
        assert catalogue_repository is not None, "The catalogue row should exist"
        catalogue_repository.is_active = False

    with capture_femto_logs(_LOGGER_NAME) as capture:
        await sync_module.sync_from_catalogue(session_factory, session_factory, "test")
        capture.wait_for_count(2)

    transitions = [
        message for message in _messages(capture) if "[INGESTION_TRANSITION]" in message
    ]
    assert len(transitions) == 1, "Only the changed toggle should be logged"
    assert "estate_key=test" in transitions[0]
    assert "slug=leynos/wildside" in transitions[0]
    assert "transition=disable_inactive" in transitions[0]
    assert "enabled=false" in transitions[0]
    assert "dry_run=false" in transitions[0]


@pytest.mark.asyncio
async def test_a_dry_run_labels_the_changes_it_rolled_back(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A preview's slug events say they describe work the run rolled back."""
    catalogue = tmp_path / "catalogue.yaml"
    await _import_catalogue(
        session_factory, catalogue, commit_sha="observability-dry-run-transition"
    )
    await sync_module.sync_from_catalogue(session_factory, session_factory, "test")

    async with session_factory() as session, session.begin():
        catalogue_repository = await session.scalar(
            select(RepositoryRecord).where(
                RepositoryRecord.owner == "leynos",
                RepositoryRecord.name == "wildside",
            )
        )
        assert catalogue_repository is not None, "The catalogue row should exist"
        catalogue_repository.is_active = False

    with capture_femto_logs(_LOGGER_NAME) as capture:
        await sync_module.sync_from_catalogue(
            session_factory,
            session_factory,
            "test",
            options=sync_module.SyncOptions(dry_run=True),
        )
        capture.wait_for_count(2)

    transitions = [
        message for message in _messages(capture) if "[INGESTION_TRANSITION]" in message
    ]
    assert len(transitions) == 1, "The preview should report the one change it saw"
    assert "slug=leynos/wildside" in transitions[0]
    assert "dry_run=true" in transitions[0], (
        "A rolled-back change must not look like a committed one"
    )
    persisted = await fetch_silver_repo(session_factory, "leynos", "wildside")
    assert persisted is not None, "The preview must leave the row in place"
    assert persisted.ingestion_enabled is True, "The preview must roll the change back"


@pytest.mark.asyncio
async def test_a_failed_run_does_not_log_the_changes_it_rolled_back(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A failure after a toggle change logs the failure only, not the change."""
    catalogue = tmp_path / "catalogue.yaml"
    await _import_catalogue(
        session_factory,
        catalogue,
        commit_sha="observability-rollback",
        names=("alpha", "zulu"),
    )
    await sync_module.sync_from_catalogue(session_factory, session_factory, "test")

    # alpha sorts before zulu, so its toggle change is recorded first and zulu's
    # insert is the write that fails. Without the ordering the run could fail
    # before any change was pending and the test would prove nothing.
    async with session_factory() as session, session.begin():
        alpha = await session.scalar(
            select(RepositoryRecord).where(RepositoryRecord.name == "alpha")
        )
        assert alpha is not None, "The catalogue row should exist"
        alpha.is_active = False
        await session.execute(
            delete(Repository).where(Repository.github_name == "zulu")
        )

    exploding = typ.cast("UpsertStrategy", _ExplodingStrategy())
    with (
        capture_femto_logs(_LOGGER_NAME) as capture,
        pytest.raises(RegistrySyncError),
    ):
        await sync_module.sync_from_catalogue(
            session_factory,
            session_factory,
            "test",
            options=sync_module.SyncOptions(upsert_strategy=exploding),
        )
    capture.wait_for_count(1)

    messages = _messages(capture)
    assert len(messages) == 1, "The failed run should log its failure only"
    assert "[SYNC_FAILED]" in messages[0]
    assert not [m for m in messages if "[INGESTION_TRANSITION]" in m], (
        "A rolled-back toggle change must not be reported as a change"
    )


@pytest.mark.asyncio
async def test_a_lost_claim_to_another_estate_records_the_conflict(
    session_factory: async_sessionmaker[AsyncSession],
    create_estates: tuple[str, str],
    create_repo: CreateRepoFn,
    tmp_path: Path,
) -> None:
    """A claim lost to another estate is reported and recorded, not dropped."""
    estate_a_id, estate_b_id = create_estates
    catalogue = tmp_path / "catalogue.yaml"
    await _import_catalogue(
        session_factory, catalogue, commit_sha="observability-lost-claim"
    )
    cat_repo = await _catalogue_repository(session_factory, "wildside")
    await create_repo("leynos", "wildside", spec=RepositoryCreateSpec())

    async with session_factory() as stale_session:
        stale_rows = await sync_module._load_silver_repositories(
            stale_session, estate_a_id, ["leynos/wildside"]
        )
        # End the read but keep the view a sync that loaded before the other
        # estate claimed the row would hold.
        await stale_session.commit()
        assert stale_rows["leynos/wildside"].estate_id is None

    async with session_factory() as winner_session:
        winner_rows = await sync_module._load_silver_repositories(
            winner_session, estate_b_id, []
        )
        claimed = await claim_unowned_repository(
            winner_session, winner_rows["leynos/wildside"], estate_b_id
        )
        assert claimed, "The first claim of an unowned row should succeed"
        await winner_session.commit()

    result = SyncResult(estate_key="estate-a")
    events = SyncEventBuffer()
    async with session_factory() as loser_session:
        context = sync_module._SilverSyncContext(
            session=loser_session,
            silver_repos=stale_rows,
            estate_key="estate-a",
            estate_id=estate_a_id,
            now=sync_module.utcnow(),
            upsert_strategy=DialectUpsertStrategy(),
            result=result,
            events=events,
        )
        await sync_module._sync_one_repository(context, "leynos/wildside", cat_repo)
        await loser_session.rollback()

    assert result.repositories_conflicted == ["leynos/wildside"], (
        "The lost claim should be reported as a conflict"
    )
    assert events.conflicts == ("leynos/wildside",), (
        "The lost claim must record a conflict event, not drop it"
    )

    with capture_femto_logs(_LOGGER_NAME) as capture:
        events.publish("estate-a", dry_run=False)
        capture.wait_for_count(1)

    message = _messages(capture)[0]
    assert "[SYNC_CONFLICTED]" in message
    assert "estate_key=estate-a" in message
    assert "slug=leynos/wildside" in message
