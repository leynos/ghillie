"""Unit tests for Bronze RawEventWriter."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import pytest
from sqlalchemy import func, select

from ghillie.bronze import (
    RawEvent,
    RawEventEnvelope,
    RawEventState,
    RawEventWriter,
    TimezoneAwareRequiredError,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_ingest_preserves_payload_and_timestamps(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ingestion stores payload verbatim and timestamps with UTC tzinfo."""
    writer = RawEventWriter(session_factory)
    payload = {
        "key": "value",
        "nested": {"list": [1, 2, 3]},
        "when": dt.datetime(2024, 6, 1, 8, 30, tzinfo=dt.timezone.utc),
    }
    occurred_at = dt.datetime(2024, 6, 1, 8, 30, tzinfo=dt.timezone.utc)

    async def _run() -> RawEvent:
        return await writer.ingest(
            RawEventEnvelope(
                source_system="github",
                source_event_id="evt-123",
                event_type="github.push",
                repo_external_id="org/repo",
                occurred_at=occurred_at,
                payload=payload,
            )
        )

    raw_event = asyncio.run(_run())
    # Ensure caller payload remains untouched after ingestion.
    assert isinstance(payload["when"], dt.datetime)

    async def _load() -> RawEvent:
        async with session_factory() as session:
            stored = await session.get(RawEvent, raw_event.id)
            assert stored is not None
            return stored

    stored_event = asyncio.run(_load())
    expected_payload = dict(payload)
    expected_payload["when"] = expected_payload["when"].isoformat()

    assert stored_event.payload == expected_payload, (
        "payload persisted verbatim in JSON form"
    )
    assert stored_event.occurred_at == occurred_at, (
        "occurred_at should round-trip unchanged"
    )
    assert stored_event.ingested_at is not None, "ingested_at should be set on insert"
    assert stored_event.ingested_at.tzinfo == dt.timezone.utc, (
        "ingested_at must be UTC-aware"
    )
    assert stored_event.transform_state == RawEventState.PENDING.value, (
        "raw event starts pending"
    )


def test_ingest_rejects_naive_occurred_at(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ingestion rejects naive occurred_at timestamps."""
    writer = RawEventWriter(session_factory)
    payload = {"ref": "refs/heads/main"}
    occurred_at = dt.datetime(2024, 6, 1, 8, 30)  # noqa: DTZ001

    async def _run() -> None:
        await writer.ingest(
            RawEventEnvelope(
                source_system="github",
                source_event_id="evt-naive",
                event_type="github.push",
                repo_external_id="org/repo",
                occurred_at=occurred_at,
                payload=payload,
            )
        )

    with pytest.raises(TimezoneAwareRequiredError):
        asyncio.run(_run())


def test_ingest_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repeated ingests of the same event return the existing row."""
    writer = RawEventWriter(session_factory)
    payload = {"id": "evt-dup"}
    occurred_at = dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)

    async def _run() -> tuple[RawEvent, RawEvent]:
        first = await writer.ingest(
            RawEventEnvelope(
                source_system="github",
                source_event_id="evt-dup",
                event_type="github.push",
                repo_external_id="org/repo",
                occurred_at=occurred_at,
                payload=payload,
            )
        )
        second = await writer.ingest(
            RawEventEnvelope(
                source_system="github",
                source_event_id="evt-dup",
                event_type="github.push",
                repo_external_id="org/repo",
                occurred_at=occurred_at,
                payload=payload,
            )
        )
        return first, second

    first, second = asyncio.run(_run())
    assert first.id == second.id

    async def _count_rows() -> int:
        async with session_factory() as session:
            return int(
                await session.scalar(select(func.count()).select_from(RawEvent)) or 0
            )

    count = asyncio.run(_count_rows())
    assert count == 1


def test_ingest_is_idempotent_under_concurrency(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Concurrent ingests of the same envelope still produce one row."""
    writer = RawEventWriter(session_factory)
    payload = {"id": "evt-dup"}
    occurred_at = dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)

    envelope = RawEventEnvelope(
        source_system="github",
        source_event_id="evt-dup",
        event_type="github.push",
        repo_external_id="org/repo",
        occurred_at=occurred_at,
        payload=payload,
    )

    async def _run_concurrent() -> list[RawEvent]:
        tasks = [writer.ingest(envelope) for _ in range(5)]
        return await asyncio.gather(*tasks)

    results = asyncio.run(_run_concurrent())
    ids = {event.id for event in results}
    assert len(ids) == 1

    async def _count_rows() -> int:
        async with session_factory() as session:
            return int(
                await session.scalar(select(func.count()).select_from(RawEvent)) or 0
            )

    count = asyncio.run(_count_rows())
    assert count == 1
