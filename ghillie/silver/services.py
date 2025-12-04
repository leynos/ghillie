"""Transformers bridging Bronze raw events into Silver staging tables."""

from __future__ import annotations

import copy
import logging
import typing as typ

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ghillie.bronze.storage import RawEvent, RawEventState
from ghillie.silver.errors import RawEventTransformError
from ghillie.silver.storage import EventFact
from ghillie.silver.transformers import get_entity_transformer

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

type ProcessedIds = list[int]
logger = logging.getLogger(__name__)


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
            processed: ProcessedIds = []
            stream = await session.stream_scalars(
                stmt.limit(limit) if limit is not None else stmt
            )
            async for raw_event in stream:
                processed.extend(await self._process_events(session, [raw_event]))
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
        """Process a sequence of raw events, collecting successfully processed IDs."""
        processed: ProcessedIds = []
        for raw_event in events:
            processed_id = await self._process_single_event(session, raw_event)
            if processed_id is not None:
                processed.append(processed_id)
        return processed

    async def _process_single_event(
        self, session: AsyncSession, raw_event: RawEvent
    ) -> int | None:
        """Process a single raw event, returning its ID if processed successfully."""
        try:
            async with session.begin_nested():
                await self._upsert_event_fact(session, raw_event)
                await self._apply_entity_transform(session, raw_event)
            return self._mark_processed(raw_event)
        except RawEventTransformError as exc:
            return await self._handle_transform_error(session, raw_event, exc)

    async def _apply_entity_transform(
        self, session: AsyncSession, raw_event: RawEvent
    ) -> None:
        """Apply an entity-specific transformation when one is registered."""
        transformer = get_entity_transformer(raw_event.event_type)
        if transformer is None:
            return

        try:
            await transformer(session, raw_event)
        except RawEventTransformError:
            raise
        except Exception as exc:
            raise RawEventTransformError.entity_transform_failed(exc) from exc

    async def _handle_transform_error(
        self, session: AsyncSession, raw_event: RawEvent, exc: RawEventTransformError
    ) -> int | None:
        """Handle transform errors, possibly recovering from concurrent inserts."""
        if exc.reason == "concurrent_insert":
            recovered_id = await self._try_recover_concurrent_insert(session, raw_event)
            if recovered_id is not None:
                return recovered_id

        self._mark_failed(raw_event, exc)
        return None

    async def _try_recover_concurrent_insert(
        self, session: AsyncSession, raw_event: RawEvent
    ) -> int | None:
        """Try to recover from a concurrent insert by checking if EventFact exists."""
        existing = await session.scalar(
            select(EventFact).where(EventFact.raw_event_id == raw_event.id)
        )
        if existing is not None:
            return self._mark_processed(raw_event)
        return None

    def _mark_processed(self, raw_event: RawEvent) -> int:
        """Mark raw event as processed and return its ID."""
        raw_event.transform_state = RawEventState.PROCESSED.value
        raw_event.transform_error = None
        return raw_event.id

    def _mark_failed(self, raw_event: RawEvent, exc: RawEventTransformError) -> None:
        """Mark raw event as failed and log the error."""
        raw_event.transform_state = RawEventState.FAILED.value
        raw_event.transform_error = str(exc)
        logger.warning(
            "RawEvent %s (%s) failed transform: %s",
            raw_event.id,
            raw_event.event_type,
            exc,
        )

    @staticmethod
    async def _upsert_event_fact(
        session: AsyncSession, raw_event: RawEvent
    ) -> EventFact:
        raw_event_id = raw_event.id

        existing = await session.scalar(
            select(EventFact).where(EventFact.raw_event_id == raw_event_id)
        )
        if existing is not None:
            if existing.payload != raw_event.payload:
                raise RawEventTransformError.payload_mismatch()
            return existing

        fact = EventFact(
            raw_event_id=raw_event_id,
            repo_external_id=raw_event.repo_external_id,
            event_type=raw_event.event_type,
            occurred_at=raw_event.occurred_at,
            payload=copy.deepcopy(raw_event.payload),
        )

        try:
            async with session.begin_nested():
                session.add(fact)
                await session.flush()
        except IntegrityError as exc:
            with session.no_autoflush:
                existing = await session.scalar(
                    select(EventFact).where(EventFact.raw_event_id == raw_event_id)
                )
            if existing is not None:
                return existing
            raise RawEventTransformError.concurrent_insert() from exc

        return fact
