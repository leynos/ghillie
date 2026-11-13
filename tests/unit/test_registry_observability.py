"""Unit tests for the events a registry sync emits.

The events are asserted through the house femtologging capture helper, so the
tests pin the text an operator would actually read rather than a mock call.
"""

from __future__ import annotations

import contextlib
import typing as typ

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ghillie.catalogue import CatalogueImporter
from ghillie.catalogue.storage import RepositoryRecord
from ghillie.registry import sync as sync_module
from ghillie.registry.errors import RegistrySyncError
from ghillie.silver.storage import Repository
from tests.helpers.femtologging_capture import FemtoLogCapture, capture_femto_logs
from tests.unit.registry_service_sync_helpers import catalogue_naming

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


async def _import_catalogue(
    session_factory: async_sessionmaker[AsyncSession],
    catalogue_path: Path,
    *,
    commit_sha: str,
) -> None:
    """Import a catalogue naming the one repository these tests use."""
    catalogue_path.write_text(catalogue_naming(("wildside",)), encoding="utf-8")
    importer = CatalogueImporter(session_factory, estate_key="test")
    await importer.import_path(catalogue_path, commit_sha=commit_sha)


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
