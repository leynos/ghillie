"""Unit tests for the Bronze raw event store and transform helpers."""
# ruff: noqa: D103

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if typ.TYPE_CHECKING:
    from pathlib import Path
else:  # pragma: no cover - hints only
    Path = typ.Any

from ghillie.bronze import (
    RawEvent,
    RawEventEnvelope,
    RawEventState,
    RawEventWriter,
    init_bronze_storage,
)
from ghillie.bronze.services import make_dedupe_key
from ghillie.silver import EventFact, RawEventTransformer, init_silver_storage


@pytest.fixture
def session_factory(
    tmp_path: Path,
) -> typ.Iterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bronze.db'}")
    asyncio.run(init_bronze_storage(engine))
    asyncio.run(init_silver_storage(engine))
    factory = async_sessionmaker(engine, expire_on_commit=False)

    yield factory

    asyncio.run(engine.dispose())


def test_make_dedupe_key_changes_when_inputs_change() -> None:
    occurred_at = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    base = make_dedupe_key(
        RawEventEnvelope(
            source_system="github",
            event_type="github.push",
            source_event_id="evt-1",
            repo_external_id="org/repo",
            occurred_at=occurred_at,
            payload={"a": 1},
        )
    )
    changed_repo = make_dedupe_key(
        RawEventEnvelope(
            source_system="github",
            event_type="github.push",
            source_event_id="evt-1",
            repo_external_id="org/other",
            occurred_at=occurred_at,
            payload={"a": 1},
        )
    )
    changed_payload = make_dedupe_key(
        RawEventEnvelope(
            source_system="github",
            event_type="github.push",
            source_event_id="evt-1",
            repo_external_id="org/repo",
            occurred_at=occurred_at,
            payload={"a": 2},
        )
    )

    assert base != changed_repo
    assert base != changed_payload


def test_ingest_preserves_payload_and_timestamps(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
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

    async def _load() -> RawEvent:
        async with session_factory() as session:
            stored = await session.get(RawEvent, raw_event.id)
            assert stored is not None
            return stored

    stored_event = asyncio.run(_load())
    expected_payload = dict(payload)
    expected_payload["when"] = expected_payload["when"].isoformat()

    assert stored_event.payload == expected_payload
    assert stored_event.occurred_at == occurred_at
    assert stored_event.ingested_at is not None
    assert stored_event.transform_state == RawEventState.PENDING.value


def test_ingest_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
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


def test_transformer_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    payload = {"id": "evt-dup", "value": 3}
    occurred_at = dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)

    async def _ingest_and_transform() -> RawEvent:
        raw_event = await writer.ingest(
            RawEventEnvelope(
                source_system="github",
                source_event_id="evt-dup",
                event_type="github.push",
                repo_external_id="org/repo",
                occurred_at=occurred_at,
                payload=payload,
            )
        )
        await transformer.process_pending()
        await transformer.process_raw_event_ids([raw_event.id])
        return raw_event

    raw_event = asyncio.run(_ingest_and_transform())

    async def _assert_state() -> None:
        async with session_factory() as session:
            facts = (await session.scalars(select(EventFact))).all()
            assert len(facts) == 1
            fact = facts[0]
            assert fact.raw_event_id == raw_event.id
            assert fact.payload == payload

            stored_event = await session.get(RawEvent, raw_event.id)
            assert stored_event is not None
            assert stored_event.transform_state == RawEventState.PROCESSED.value
            assert stored_event.transform_error is None

    asyncio.run(_assert_state())


async def _insert_event_fact(
    session_factory: async_sessionmaker[AsyncSession],
    raw_event_id: int,
    payload: dict[str, object] | None = None,
) -> None:
    async with session_factory() as session, session.begin():
        fact = EventFact(
            raw_event_id=raw_event_id,
            repo_external_id="org/repo",
            event_type="github.push",
            occurred_at=dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc),
            payload=payload or {"value": 3},
        )
        session.add(fact)


def test_transformer_handles_concurrent_insert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Treat uniqueness conflicts as already-processed instead of failures."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    payload = {"id": "evt-race"}
    occurred_at = dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)

    async def _run() -> None:
        raw_event = await writer.ingest(
            RawEventEnvelope(
                source_system="github",
                source_event_id="evt-race",
                event_type="github.push",
                repo_external_id="org/repo",
                occurred_at=occurred_at,
                payload=payload,
            )
        )
        await _insert_event_fact(session_factory, raw_event.id, payload)
        async with session_factory() as session:
            stored_event = await session.get(RawEvent, raw_event.id)
            assert stored_event is not None

            flush_orig = session.flush

            async def flush_wrapper(
                objects: typ.Sequence[object] | None = None,
            ) -> None:
                raise IntegrityError(
                    "",
                    {},
                    Exception("duplicate"),
                    connection_invalidated=False,
                )

            session.flush = flush_wrapper  # type: ignore[assignment]
            # Should not raise; should treat as already-processed because fact exists.
            fact = await transformer._upsert_event_fact(session, stored_event)
            session.flush = flush_orig  # type: ignore[assignment]

            assert fact.raw_event_id == raw_event.id
            assert fact.payload == payload

    asyncio.run(_run())
