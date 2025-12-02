"""Unit tests for the Bronze raw event store and transform helpers."""
# ruff: noqa: D103

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import pytest
import sqlalchemy as sa
from sqlalchemy import func, select
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
    TimezoneAwareRequiredError,
    init_bronze_storage,
)
from ghillie.bronze.services import make_dedupe_key
from ghillie.silver import EventFact, RawEventTransformer, init_silver_storage
from ghillie.silver.services import RawEventTransformError


@pytest.fixture
def session_factory(
    tmp_path: Path,
) -> typ.Iterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bronze.db'}")
    asyncio.run(init_bronze_storage(engine))
    asyncio.run(init_silver_storage(engine))

    yield async_sessionmaker(engine, expire_on_commit=False)

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


def test_make_dedupe_key_rejects_naive_occurred_at() -> None:
    envelope = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-naive",
        repo_external_id="org/repo",
        occurred_at=dt.datetime(2024, 1, 1, 12, 0),  # noqa: DTZ001
        payload={"a": 1},
    )

    with pytest.raises(TimezoneAwareRequiredError) as excinfo:
        make_dedupe_key(envelope)
    assert "occurred_at" in str(excinfo.value)


def test_make_dedupe_key_normalizes_occurred_at_timezones() -> None:
    instant_utc = dt.datetime(2024, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
    instant_offset = instant_utc.astimezone(dt.timezone(dt.timedelta(hours=1)))

    envelope_utc = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-1",
        repo_external_id="org/repo",
        occurred_at=instant_utc,
        payload={"a": 1},
    )
    envelope_offset = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-1",
        repo_external_id="org/repo",
        occurred_at=instant_offset,
        payload={"a": 1},
    )

    assert make_dedupe_key(envelope_utc) == make_dedupe_key(envelope_offset)


def test_make_dedupe_key_payload_determinism_and_timezone_awareness() -> None:
    occurred_at = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    payload_a = {"a": 1, "b": 2}
    payload_b = {"b": 2, "a": 1}

    env_a = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-1",
        repo_external_id="org/repo",
        occurred_at=occurred_at,
        payload=payload_a,
    )
    env_b = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-1",
        repo_external_id="org/repo",
        occurred_at=occurred_at,
        payload=payload_b,
    )

    assert make_dedupe_key(env_a) == make_dedupe_key(env_b)

    env_aware = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-2",
        repo_external_id="org/repo",
        occurred_at=occurred_at,
        payload={
            "timestamp": dt.datetime(2024, 1, 1, 12, 0, tzinfo=dt.timezone.utc),
            "value": 42,
        },
    )

    assert make_dedupe_key(env_aware) == make_dedupe_key(env_aware)

    env_naive = RawEventEnvelope(
        source_system="github",
        event_type="github.push",
        source_event_id="evt-3",
        repo_external_id="org/repo",
        occurred_at=occurred_at,
        payload={"timestamp": dt.datetime(2024, 1, 1, 12, 0), "value": 42},  # noqa: DTZ001
    )

    with pytest.raises(TimezoneAwareRequiredError) as excinfo:
        make_dedupe_key(env_naive)
    assert "payload" in str(excinfo.value).lower()


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


def test_ingest_rejects_naive_occurred_at(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
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


def test_utc_datetime_normalises_results(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    naive_str = "2024-06-01 12:00:00"

    async def _seed() -> None:
        async with session_factory() as session, session.begin():
            await session.execute(
                sa.text(
                    """
                    INSERT INTO raw_events
                    (source_system, event_type, occurred_at, ingested_at, dedupe_key,
                     payload, transform_state)
                    VALUES ('github', 'push', :occurred_at, :occurred_at, 'key',
                            '{}', 0)
                    """
                ),
                {"occurred_at": naive_str},
            )

    asyncio.run(_seed())

    async def _load() -> RawEvent:
        async with session_factory() as session:
            return (await session.execute(select(RawEvent))).scalar_one()

    raw_event = asyncio.run(_load())
    assert raw_event.occurred_at.tzinfo is not None
    assert raw_event.occurred_at.utcoffset() == dt.timedelta(0)


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
    """Treat existing EventFacts as processed even if a race already wrote one."""
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


def test_transformer_marks_failed_on_payload_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    original_payload = {"id": "evt-conflict", "value": 1}
    conflicting_payload = {"id": "evt-conflict", "value": 999}
    occurred_at = dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)

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


def test_transformer_marks_failed_on_concurrent_insert_integrity_error(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    payload = {"id": "evt-concurrent-insert", "value": 42}
    occurred_at = dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)

    async def _ingest() -> RawEvent:
        return await writer.ingest(
            RawEventEnvelope(
                source_system="github",
                source_event_id="evt-concurrent-insert",
                event_type="github.push",
                repo_external_id="org/repo",
                occurred_at=occurred_at,
                payload=payload,
            )
        )

    async def _failing_upsert(*_: object, **__: object) -> EventFact:
        raise RawEventTransformError.concurrent_insert()

    monkeypatch.setattr(
        transformer, "_upsert_event_fact", _failing_upsert, raising=True
    )

    async def _run() -> None:
        raw_event = await _ingest()
        await _verify_transformation_failure(
            session_factory, transformer, raw_event, "concurrent"
        )

    asyncio.run(_run())


def test_process_pending_respects_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    async def _run() -> None:
        envelopes = [
            RawEventEnvelope(
                source_system="github",
                event_type="push",
                source_event_id=f"evt-limit-{i}",
                repo_external_id="org/repo",
                occurred_at=dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc),
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
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    async def _run() -> None:
        envelope = RawEventEnvelope(
            source_system="github",
            event_type="push",
            source_event_id="evt-empty-input",
            repo_external_id="org/repo",
            occurred_at=dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc),
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
