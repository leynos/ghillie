"""Services for persisting Bronze raw events."""

from __future__ import annotations

import copy
import dataclasses as dc
import datetime as dt
import hashlib
import json
import typing as typ

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ghillie.bronze.storage import RawEvent

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Payload = dict[str, typ.Any]


class TimezoneAwareRequiredError(ValueError):
    """Raised when datetime inputs lack timezone information."""

    def __init__(self, context: str) -> None:
        """Attach a consistent error message for the failing context."""
        super().__init__(f"{context} must be timezone aware")

    @classmethod
    def for_payload(cls) -> TimezoneAwareRequiredError:
        """Return an error indicating payload timestamps were naive."""
        return cls("payload datetime values")

    @classmethod
    def for_occurrence(cls) -> TimezoneAwareRequiredError:
        """Return an error indicating occurred_at was naive."""
        return cls("occurred_at")


class RawEventPersistError(RuntimeError):
    """Raised when dedupe checks cannot locate an expected row."""

    def __init__(self) -> None:
        """Include a deterministic error message for logging."""
        super().__init__("expected existing raw_event after rollback")


@dc.dataclass(frozen=True, slots=True)
class RawEventEnvelope:
    """Structured input for Bronze ingestion."""

    source_system: str
    event_type: str
    occurred_at: dt.datetime
    payload: Payload
    source_event_id: str | None = None
    repo_external_id: str | None = None


def _normalise_payload(payload: Payload) -> Payload:
    """Deep-copy payload converting datetimes to ISO-8601 strings."""

    def _convert(value: object) -> object:
        if isinstance(value, dict):
            return {k: _convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_convert(item) for item in value]
        if isinstance(value, dt.datetime):
            if value.tzinfo is None:
                raise TimezoneAwareRequiredError.for_payload()
            return value.astimezone(dt.timezone.utc).isoformat()
        return copy.deepcopy(value)

    return typ.cast("Payload", _convert(payload))


def _serialise_for_hash(payload: Payload) -> str:
    """Return a deterministic JSON string for hashing payloads."""

    def _default(value: object) -> object:
        if isinstance(value, dt.datetime):
            if value.tzinfo is None:
                raise TimezoneAwareRequiredError.for_payload()
            return value.astimezone(dt.timezone.utc).isoformat()
        return str(value)

    return json.dumps(
        payload,
        default=_default,
        sort_keys=True,
        separators=(",", ":"),
    )


def make_dedupe_key(envelope: RawEventEnvelope) -> str:
    """Construct a stable dedupe key used to avoid duplicate rows."""
    if envelope.occurred_at.tzinfo is None:
        raise TimezoneAwareRequiredError.for_occurrence()

    canonical_payload = _serialise_for_hash(envelope.payload)
    material = "|".join(
        [
            envelope.source_system,
            envelope.event_type,
            envelope.source_event_id or "",
            envelope.repo_external_id or "",
            envelope.occurred_at.astimezone(dt.timezone.utc).isoformat(),
            hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class RawEventWriter:
    """Append-only writer that records Bronze events."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory used for ingestion operations."""
        self._session_factory = session_factory

    async def ingest(self, envelope: RawEventEnvelope) -> RawEvent:
        """Persist a raw event if not already present.

        Idempotency is enforced via a hashed dedupe key so webhook retries or
        overlapping pollers cannot create duplicate Bronze rows. The payload is
        deep-copied to avoid accidental caller-side mutation post-ingestion.
        """
        if envelope.occurred_at.tzinfo is None:
            raise TimezoneAwareRequiredError.for_occurrence()

        payload_copy = _normalise_payload(envelope.payload)
        envelope_copy = dc.replace(envelope, payload=payload_copy)
        dedupe_key = make_dedupe_key(envelope_copy)

        async with self._session_factory() as session:
            raw_event = RawEvent(
                source_system=envelope_copy.source_system,
                source_event_id=envelope_copy.source_event_id,
                event_type=envelope_copy.event_type,
                repo_external_id=envelope_copy.repo_external_id,
                occurred_at=envelope_copy.occurred_at,
                payload=payload_copy,
                dedupe_key=dedupe_key,
            )
            session.add(raw_event)

            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self._load_existing(session, envelope_copy, dedupe_key)
                if existing is None:
                    raise RawEventPersistError from None
                return existing

            await session.refresh(raw_event)
            return raw_event

    @staticmethod
    async def _load_existing(
        session: AsyncSession,
        envelope: RawEventEnvelope,
        dedupe_key: str,
    ) -> RawEvent | None:
        stmt = select(RawEvent).where(
            RawEvent.source_system == envelope.source_system,
            RawEvent.dedupe_key == dedupe_key,
        )
        return await session.scalar(stmt)
