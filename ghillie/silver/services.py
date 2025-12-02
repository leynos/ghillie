"""Transformers bridging Bronze raw events into Silver staging tables."""

from __future__ import annotations

import copy
import typing as typ

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ghillie.bronze.storage import RawEvent, RawEventState
from ghillie.silver.storage import EventFact

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

ProcessedIds = list[int]
BATCH_SIZE = 100


class RawEventTransformError(Exception):
    """Raised when a raw event cannot be transformed deterministically."""

    @classmethod
    def payload_mismatch(cls) -> RawEventTransformError:
        """Create a payload drift error."""
        return cls("existing event fact payload no longer matches Bronze")

    @classmethod
    def concurrent_insert(cls) -> RawEventTransformError:
        """Create an error for concurrent inserts."""
        return cls("failed to insert event fact; concurrent transform?")


class RawEventTransformer:
    """Idempotent Bronze→Silver transformer for raw events."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory used by transform runs."""
        self._session_factory = session_factory

    async def process_pending(self, limit: int | None = None) -> ProcessedIds:
        """Transform pending raw events in insertion order."""
        async with self._session_factory() as session:
            stmt = (
                select(RawEvent)
                .where(RawEvent.transform_state == RawEventState.PENDING.value)
                .order_by(RawEvent.id)
            )
            remaining = limit
            processed: ProcessedIds = []
            stream = await session.stream_scalars(
                stmt.limit(limit) if limit is not None else stmt
            )
            async for raw_event in stream:
                processed.extend(await self._process_events(session, [raw_event]))
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        break
                # commit every batch to release memory/backlog
                if len(processed) % BATCH_SIZE == 0:
                    await session.commit()
            await session.commit()
            return processed

    async def process_raw_event_ids(
        self, raw_event_ids: typ.Sequence[int]
    ) -> ProcessedIds:
        """Transform the given raw events, regardless of current state."""
        if not raw_event_ids:
            return []

        async with self._session_factory() as session:
            stmt = (
                select(RawEvent)
                .where(RawEvent.id.in_(raw_event_ids))
                .order_by(RawEvent.id)
            )
            processed: ProcessedIds = []
            stream = await session.stream_scalars(stmt)
            async for raw_event in stream:
                processed.extend(await self._process_events(session, [raw_event]))
            await session.commit()
            return processed

    async def _process_events(
        self, session: AsyncSession, events: typ.Sequence[RawEvent]
    ) -> ProcessedIds:
        processed: ProcessedIds = []
        for raw_event in events:
            try:
                await self._upsert_event_fact(session, raw_event)
            except RawEventTransformError as exc:
                raw_event.transform_state = RawEventState.FAILED.value
                raw_event.transform_error = str(exc)
                continue

            raw_event.transform_state = RawEventState.PROCESSED.value
            raw_event.transform_error = None
            processed.append(raw_event.id)

        return processed

    @staticmethod
    async def _upsert_event_fact(
        session: AsyncSession, raw_event: RawEvent
    ) -> EventFact:
        existing = await session.scalar(
            select(EventFact).where(EventFact.raw_event_id == raw_event.id)
        )
        if existing is not None:
            if existing.payload != raw_event.payload:
                raise RawEventTransformError.payload_mismatch()
            return existing

        fact = EventFact(
            raw_event_id=raw_event.id,
            repo_external_id=raw_event.repo_external_id,
            event_type=raw_event.event_type,
            occurred_at=raw_event.occurred_at,
            payload=copy.deepcopy(raw_event.payload),
        )
        session.add(fact)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            with session.no_autoflush:
                existing = await session.scalar(
                    select(EventFact).where(EventFact.raw_event_id == raw_event.id)
                )
            if existing is not None:
                return existing
            raise RawEventTransformError.concurrent_insert() from exc
        return fact
