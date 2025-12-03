"""Unit tests for Silver RawEventTransformer."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ghillie.bronze import (
    RawEvent,
    RawEventEnvelope,
    RawEventState,
    RawEventWriter,
)
from ghillie.silver import EventFact, RawEventTransformer
from ghillie.silver.services import RawEventTransformError

if typ.TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


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
            occurred_at=dt.datetime(2024, 6, 1, tzinfo=dt.UTC),
            payload=payload or {"value": 3},
        )
        session.add(fact)


async def _verify_transformation_failure(
    session_factory: async_sessionmaker[AsyncSession],
    transformer: RawEventTransformer,
    raw_event: RawEvent,
    expected_error_keyword: str,
) -> None:
    processed_ids = await transformer.process_raw_event_ids([raw_event.id])
    assert raw_event.id not in processed_ids

    async with session_factory() as session:
        reloaded = await session.get(RawEvent, raw_event.id)
        assert reloaded is not None
        assert reloaded.transform_state == RawEventState.FAILED.value
        assert reloaded.transform_error is not None
        assert expected_error_keyword in reloaded.transform_error.lower()


def test_transformer_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Transformer produces one fact and marks raw event processed."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    payload = {"id": "evt-dup", "value": 3}
    occurred_at = dt.datetime(2024, 6, 1, tzinfo=dt.UTC)

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


def test_transformer_handles_concurrent_insert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Treat existing EventFacts as processed even if a race already wrote one."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    payload = {"id": "evt-race"}
    occurred_at = dt.datetime(2024, 6, 1, tzinfo=dt.UTC)

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
        processed = await transformer.process_raw_event_ids([raw_event.id])
        assert processed == [raw_event.id]

        async with session_factory() as session:
            facts = (await session.scalars(select(EventFact))).all()
            assert len(facts) == 1
            stored_event = await session.get(RawEvent, raw_event.id)
            assert stored_event is not None
            assert stored_event.transform_state == RawEventState.PROCESSED.value
            assert stored_event.transform_error is None

    asyncio.run(_run())


def test_transformer_marks_failed_on_payload_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Payload drift between EventFact and RawEvent marks failure."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    original_payload = {"id": "evt-conflict", "value": 1}
    conflicting_payload = {"id": "evt-conflict", "value": 999}
    occurred_at = dt.datetime(2024, 6, 1, tzinfo=dt.UTC)

    async def _setup_conflict() -> RawEvent:
        raw_event = await writer.ingest(
            RawEventEnvelope(
                source_system="github",
                source_event_id="evt-conflict",
                event_type="github.push",
                repo_external_id="org/repo",
                occurred_at=occurred_at,
                payload=original_payload,
            )
        )
        await _insert_event_fact(session_factory, raw_event.id, conflicting_payload)
        return raw_event

    async def _run() -> None:
        raw_event = await _setup_conflict()
        await _verify_transformation_failure(
            session_factory, transformer, raw_event, "payload"
        )

    asyncio.run(_run())


def test_transformer_treats_concurrent_insert_as_processed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: MonkeyPatch,
) -> None:
    """IntegrityError race is treated as success when another worker won."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    payload = {"id": "evt-concurrent-insert", "value": 42}
    occurred_at = dt.datetime(2024, 6, 1, tzinfo=dt.UTC)

    async def _setup() -> RawEvent:
        raw_event = await writer.ingest(
            RawEventEnvelope(
                source_system="github",
                source_event_id="evt-concurrent-insert",
                event_type="github.push",
                repo_external_id="org/repo",
                occurred_at=occurred_at,
                payload=payload,
            )
        )
        await _insert_event_fact(session_factory, raw_event.id, payload)
        return raw_event

    raw_event = asyncio.run(_setup())

    async def _raise_concurrent(*_: object, **__: object) -> EventFact:
        raise RawEventTransformError.concurrent_insert()

    monkeypatch.setattr(
        transformer, "_upsert_event_fact", _raise_concurrent, raising=True
    )

    async def _run() -> None:
        processed_ids = await transformer.process_raw_event_ids([raw_event.id])
        assert processed_ids == [raw_event.id]

        async with session_factory() as session:
            stored_event = await session.get(RawEvent, raw_event.id)
            assert stored_event is not None
            assert stored_event.transform_state == RawEventState.PROCESSED.value
            assert stored_event.transform_error is None

            facts = (await session.scalars(select(EventFact))).all()
            assert len(facts) == 1
            assert facts[0].payload == payload

    asyncio.run(_run())


def test_process_events_integrity_error_does_not_rollback_prior_events(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: MonkeyPatch,
) -> None:
    """IntegrityError on one event should not discard earlier successes."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    payload = {"id": "evt-batch"}
    occurred_at = dt.datetime(2024, 6, 1, tzinfo=dt.UTC)

    async def _ingest() -> list[RawEvent]:
        return [
            await writer.ingest(
                RawEventEnvelope(
                    source_system="github",
                    source_event_id=f"evt-batch-{i}",
                    event_type="github.push",
                    repo_external_id="org/repo",
                    occurred_at=occurred_at,
                    payload=payload | {"value": i},
                )
            )
            for i in range(2)
        ]

    raw_events = asyncio.run(_ingest())

    original_flush = AsyncSession.flush
    flush_calls = {"count": 0, "fail_at": 2}

    async def _flaky_flush(
        self: AsyncSession, objects: typ.Sequence[object] | None = None
    ) -> None:
        flush_calls["count"] += 1
        if flush_calls["count"] == flush_calls["fail_at"]:
            raise IntegrityError(None, None, Exception("simulated duplicate"))
        return await original_flush(self, objects)

    monkeypatch.setattr(AsyncSession, "flush", _flaky_flush, raising=True)

    async def _run() -> None:
        async with session_factory() as session:
            events = (
                await session.scalars(select(RawEvent).order_by(RawEvent.id))
            ).all()
            processed = await transformer._process_events(session, events)
            await session.commit()

        assert processed == [raw_events[0].id]

        async with session_factory() as session:
            facts = (await session.scalars(select(EventFact))).all()
            assert len(facts) == 1
            assert facts[0].raw_event_id == raw_events[0].id

            first = await session.get(RawEvent, raw_events[0].id)
            second = await session.get(RawEvent, raw_events[1].id)
            assert first is not None
            assert second is not None
            assert first.transform_state == RawEventState.PROCESSED.value
            assert second.transform_state == RawEventState.FAILED.value

    asyncio.run(_run())


def test_process_pending_respects_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """process_pending limit processes only the requested batch size."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    async def _run() -> None:
        envelopes = [
            RawEventEnvelope(
                source_system="github",
                event_type="push",
                source_event_id=f"evt-limit-{i}",
                repo_external_id="org/repo",
                occurred_at=dt.datetime(2024, 6, 1, tzinfo=dt.UTC),
                payload={"id": f"evt-limit-{i}"},
            )
            for i in range(3)
        ]
        for env in envelopes:
            await writer.ingest(env)

        processed_first = await transformer.process_pending(limit=1)
        assert len(processed_first) == 1

        async with session_factory() as session:
            events = (await session.scalars(select(RawEvent))).all()
        pending_after_first = [
            e for e in events if e.transform_state == RawEventState.PENDING.value
        ]
        expected_pending_after_first = 2
        assert len(pending_after_first) == expected_pending_after_first

        processed_rest = await transformer.process_pending()
        assert len(processed_rest) == expected_pending_after_first

        async with session_factory() as session:
            events_final = (await session.scalars(select(RawEvent))).all()
        pending_after_second = [
            e for e in events_final if e.transform_state == RawEventState.PENDING.value
        ]
        assert len(pending_after_second) == 0

    asyncio.run(_run())


def test_process_raw_event_ids_empty_input_noop(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Empty input to process_raw_event_ids performs no work."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    async def _run() -> None:
        envelope = RawEventEnvelope(
            source_system="github",
            event_type="push",
            source_event_id="evt-empty-input",
            repo_external_id="org/repo",
            occurred_at=dt.datetime(2024, 6, 1, tzinfo=dt.UTC),
            payload={"id": "evt-empty-input"},
        )
        stored = await writer.ingest(envelope)

        result_ids = await transformer.process_raw_event_ids([])
        assert result_ids == []

        async with session_factory() as session:
            result = await session.get(RawEvent, stored.id)
            assert result is not None
            assert result.transform_state == RawEventState.PENDING.value

    asyncio.run(_run())
