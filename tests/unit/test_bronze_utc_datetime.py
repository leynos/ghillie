"""Unit tests for Bronze UTCDateTime TypeDecorator."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import StatementError

from ghillie.bronze import RawEvent, TimezoneAwareRequiredError

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_utc_datetime_normalises_results(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SQLite returns UTC-aware datetimes via the UTCDateTime type."""
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


def test_utc_datetime_bind_rejects_naive(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Binding naive datetimes raises a timezone-required error."""

    async def _run() -> None:
        async with session_factory() as session, session.begin():
            session.add(
                RawEvent(
                    source_system="github",
                    event_type="push",
                    occurred_at=dt.datetime(2024, 6, 1, 12, 0),  # noqa: DTZ001
                    ingested_at=dt.datetime(2024, 6, 1, 12, 0, tzinfo=dt.UTC),
                    dedupe_key="key",
                    payload={},
                )
            )

    with pytest.raises(StatementError) as excinfo:
        asyncio.run(_run())
    assert isinstance(excinfo.value.__cause__, TimezoneAwareRequiredError)


def test_utc_datetime_bind_normalises_non_utc(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Binding non-UTC datetimes stores and reads back as UTC."""
    occurred_local = dt.datetime(
        2024, 6, 1, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=3))
    )
    expected_utc = occurred_local.astimezone(dt.UTC)

    async def _run() -> RawEvent:
        async with session_factory() as session, session.begin():
            raw_event = RawEvent(
                source_system="github",
                event_type="push",
                occurred_at=occurred_local,
                ingested_at=expected_utc,
                dedupe_key="key-norm",
                payload={},
            )
            session.add(raw_event)
        async with session_factory() as session:
            return (await session.execute(select(RawEvent))).scalar_one()

    stored = asyncio.run(_run())
    assert stored.occurred_at.tzinfo is not None
    assert stored.occurred_at == expected_utc
    assert stored.occurred_at.utcoffset() == dt.timedelta(0)
