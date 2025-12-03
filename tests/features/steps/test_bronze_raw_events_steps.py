"""Behavioural coverage for the Bronze raw event store."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import pytest
from pytest_bdd import given, scenario, then, when
from sqlalchemy import select

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ghillie.bronze import (
    RawEvent,
    RawEventEnvelope,
    RawEventState,
    RawEventWriter,
    TimezoneAwareRequiredError,
)
from ghillie.silver import EventFact, RawEventTransformer

EVENT_TYPE = "github.push"
SOURCE_SYSTEM = "github"
SOURCE_EVENT_ID = "evt-123"
REPO_SLUG = "octo/reef"


class BronzeContext(typ.TypedDict, total=False):
    """Shared mutable scenario state."""

    session_factory: async_sessionmaker[AsyncSession]
    writer: RawEventWriter
    transformer: RawEventTransformer
    payload: dict[str, object]
    occurred_at: dt.datetime
    raw_event_id: int
    error: Exception


@scenario(
    "../bronze_raw_events.feature",
    "GitHub events are captured immutably and transform idempotently",
)
def test_bronze_raw_event_store_behaviour() -> None:
    """Wrap the pytest-bdd scenario."""


@scenario(
    "../bronze_raw_events.feature",
    "Ingesting a GitHub event with a naive occurred_at fails",
)
def test_bronze_raw_event_rejects_naive_occurred_at() -> None:
    """Naive occurred_at values should be rejected."""


@scenario(
    "../bronze_raw_events.feature",
    "EventFact mismatch marks the raw event failed without duplicates",
)
def test_bronze_raw_event_mismatch_marks_failed() -> None:
    """Mismatched payloads should mark raw events failed."""


@pytest.fixture
def bronze_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> BronzeContext:
    """Provision a fresh database and helpers for the scenario."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    return {
        "session_factory": session_factory,
        "writer": writer,
        "transformer": transformer,
    }


@given("an empty Bronze and Silver store")
def given_empty_store(bronze_context: BronzeContext) -> None:
    """Ensure Bronze/Silver storage is initialised for the scenario."""


@given("a raw GitHub push event payload")
def raw_github_payload(bronze_context: BronzeContext) -> None:
    """Capture a canonical GitHub push payload for reuse across steps."""
    bronze_context["payload"] = {
        "after": "abc123",
        "base_ref": None,
        "commits": [
            {"id": "abc123", "message": "initial commit"},
            {"id": "def456", "message": "second commit"},
        ],
        "repository": {"full_name": REPO_SLUG},
        "ref": "refs/heads/main",
        "pusher": {"name": "marina"},
    }
    bronze_context["occurred_at"] = dt.datetime(2024, 7, 1, 12, 0, tzinfo=dt.UTC)


@given("a raw GitHub push event payload with a naive occurred_at")
def raw_github_payload_naive(bronze_context: BronzeContext) -> None:
    """Capture a payload with naive occurred_at for error checks."""
    bronze_context["payload"] = {
        "after": "abc123",
        "repository": {"full_name": REPO_SLUG},
    }
    bronze_context["occurred_at"] = dt.datetime(2024, 7, 1, 12, 0)  # noqa: DTZ001 - intentional naive test payload


@when("I ingest the raw event twice")
def ingest_raw_event_twice(bronze_context: BronzeContext) -> None:
    """Persist the same raw event twice to assert deduplication."""
    assert "payload" in bronze_context
    payload = bronze_context["payload"]
    occurred_at = bronze_context.get(
        "occurred_at", dt.datetime(2024, 7, 1, 12, 0, tzinfo=dt.UTC)
    )
    envelope = RawEventEnvelope(
        source_system=SOURCE_SYSTEM,
        source_event_id=SOURCE_EVENT_ID,
        event_type=EVENT_TYPE,
        repo_external_id=REPO_SLUG,
        occurred_at=occurred_at,
        payload=payload,
    )

    async def _ingest() -> None:
        writer = bronze_context["writer"]
        first = await writer.ingest(envelope)
        second = await writer.ingest(envelope)
        bronze_context["raw_event_id"] = first.id
        assert first.id == second.id, "duplicate ingests should resolve to same row"

    asyncio.run(_ingest())


@when("I ingest the raw event expecting a timezone error")
def ingest_raw_event_timezone_error(bronze_context: BronzeContext) -> None:
    """Attempt ingestion that should fail due to naive datetime."""
    assert "payload" in bronze_context
    occurred_at = bronze_context["occurred_at"]
    payload = bronze_context["payload"]

    async def _ingest() -> None:
        writer = bronze_context["writer"]
        await writer.ingest(
            RawEventEnvelope(
                source_system=SOURCE_SYSTEM,
                source_event_id=SOURCE_EVENT_ID,
                event_type=EVENT_TYPE,
                repo_external_id=REPO_SLUG,
                occurred_at=occurred_at,
                payload=payload,
            )
        )

    with pytest.raises(TimezoneAwareRequiredError) as excinfo:
        asyncio.run(_ingest())
    bronze_context["error"] = excinfo.value


@then("the Bronze store contains exactly one raw event row")
def assert_single_raw_event(bronze_context: BronzeContext) -> None:
    """Ensure dedupe rules keep the Bronze table append-only per event."""

    async def _count() -> int:
        async with bronze_context["session_factory"]() as session:
            rows = (await session.scalars(select(RawEvent))).all()
            return len(rows)

    count = asyncio.run(_count())
    assert count == 1, f"expected 1 raw event row but found {count}"


@then("the stored payload matches the submitted payload")
def assert_payload_preserved(bronze_context: BronzeContext) -> None:
    """Verify Bronze retains the payload exactly as ingested."""
    assert "payload" in bronze_context
    expected_payload = bronze_context["payload"]
    raw_event_id = bronze_context["raw_event_id"]

    async def _load() -> RawEvent:
        async with bronze_context["session_factory"]() as session:
            raw_event = await session.get(RawEvent, raw_event_id)
            assert raw_event is not None, "raw event missing from database"
            return raw_event

    raw_event = asyncio.run(_load())
    assert raw_event.payload == expected_payload, (
        "Bronze payload should be preserved verbatim"
    )
    assert raw_event.transform_state == RawEventState.PENDING.value


@when("I transform pending raw events")
def transform_pending(bronze_context: BronzeContext) -> None:
    """Run the Bronze→Silver transform once."""
    asyncio.run(bronze_context["transformer"].process_pending())


@when("I transform pending raw events again")
def transform_pending_again(bronze_context: BronzeContext) -> None:
    """Re-run the transform to validate idempotency."""
    asyncio.run(
        bronze_context["transformer"].process_raw_event_ids(
            [bronze_context["raw_event_id"]]
        )
    )


@when("I corrupt the raw event payload to differ from its event fact")
def corrupt_raw_event_payload(bronze_context: BronzeContext) -> None:
    """Mutate the raw event payload and reset to pending for reprocessing."""

    async def _mutate() -> None:
        async with bronze_context["session_factory"]() as session, session.begin():
            raw = await session.get(RawEvent, bronze_context["raw_event_id"])
            assert raw is not None
            raw.payload = {"after": "corrupted"}
            raw.transform_state = RawEventState.PENDING.value

    asyncio.run(_mutate())


@then("a single event fact exists for the raw event")
def assert_single_event_fact(bronze_context: BronzeContext) -> None:
    """Ensure Silver records link back to the originating Bronze row."""

    async def _count() -> tuple[int, int | None]:
        async with bronze_context["session_factory"]() as session:
            facts = (await session.scalars(select(EventFact))).all()
            raw_event = await session.get(RawEvent, bronze_context["raw_event_id"])
            assert raw_event is not None, "raw event should still exist"
            return len(facts), raw_event.transform_state

    fact_count, transform_state = asyncio.run(_count())
    assert fact_count == 1, f"expected 1 event fact, got {fact_count}"
    assert transform_state == RawEventState.PROCESSED.value


@then("the event fact payload matches the Bronze payload")
def assert_event_fact_payload(bronze_context: BronzeContext) -> None:
    """Cross-check payload fidelity between Bronze and Silver."""

    async def _load() -> tuple[dict[str, object], dict[str, object]]:
        async with bronze_context["session_factory"]() as session:
            fact = await session.scalar(select(EventFact))
            raw_event = await session.get(RawEvent, bronze_context["raw_event_id"])
            assert fact is not None, "expected event fact row"
            assert raw_event is not None, "expected raw event row"
            return raw_event.payload, fact.payload

    bronze_payload, fact_payload = asyncio.run(_load())
    assert bronze_payload == fact_payload, (
        "Silver event facts should mirror Bronze payloads"
    )


@then("a timezone error is raised during ingestion")
def assert_timezone_error(bronze_context: BronzeContext) -> None:
    """Confirm the stored error is a timezone awareness failure."""
    assert "error" in bronze_context
    assert isinstance(bronze_context["error"], TimezoneAwareRequiredError)


@then("the raw event is marked failed with a payload mismatch")
def assert_raw_event_marked_failed(bronze_context: BronzeContext) -> None:
    """Ensure corrupted payload leads to FAILED state."""

    async def _load() -> RawEvent:
        async with bronze_context["session_factory"]() as session:
            raw = await session.get(RawEvent, bronze_context["raw_event_id"])
            assert raw is not None
            return raw

    raw_event = asyncio.run(_load())
    assert raw_event.transform_state == RawEventState.FAILED.value
    assert raw_event.transform_error is not None
    assert "payload" in raw_event.transform_error.lower()


@then("the EventFact count remains one")
def assert_event_fact_count_one(bronze_context: BronzeContext) -> None:
    """Verify no duplicate EventFacts were created."""

    async def _count() -> int:
        async with bronze_context["session_factory"]() as session:
            return len((await session.scalars(select(EventFact))).all())

    count = asyncio.run(_count())
    assert count == 1
