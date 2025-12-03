"""Services for persisting Bronze raw events."""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import hashlib
import json
import typing as typ

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ghillie.bronze.errors import (
    TimezoneAwareRequiredError,
    UnsupportedPayloadTypeError,
)
from ghillie.bronze.storage import RawEvent

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Payload: typ.TypeAlias = dict[str, typ.Any]
JSONValue: typ.TypeAlias = (
    dict[str, typ.Any] | list[typ.Any] | str | int | float | bool | None
)


def _normalise_datetime_for_payload(value: dt.datetime) -> str:
    if value.tzinfo is None:
        raise TimezoneAwareRequiredError.for_payload()
    return value.astimezone(dt.timezone.utc).isoformat()


def _normalise_mapping(value: dict[typ.Any, typ.Any]) -> dict[str, JSONValue]:
    return {str(k): _normalise_payload(v) for k, v in value.items()}


def _normalise_sequence(value: list[typ.Any]) -> list[JSONValue]:
    return [_normalise_payload(item) for item in value]


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


def _normalise_payload(payload: object) -> JSONValue:
    """Deep-copy payload converting datetimes and rejecting unsupported types.

    Supported types: dict, list, str, int, float, bool, None, and datetime
    (timezone-aware). Any other type raises UnsupportedPayloadTypeError to keep
    hashing deterministic and JSON-safe.
    """
    match payload:
        case dict():
            return _normalise_mapping(payload)
        case list():
            return _normalise_sequence(payload)
        case dt.datetime():
            return _normalise_datetime_for_payload(payload)
        case None | bool() | int() | float() | str():
            return payload
        case _:
            raise UnsupportedPayloadTypeError(type(payload).__name__)


def _serialise_for_hash(payload: Payload, *, is_normalised: bool = False) -> str:
    """Return a deterministic JSON string for hashing payloads."""
    return json.dumps(
        payload if is_normalised else _normalise_payload(payload),
        sort_keys=True,
        separators=(",", ":"),
    )


def make_dedupe_key(
    envelope: RawEventEnvelope, *, payload_is_normalised: bool = False
) -> str:
    """Construct a stable dedupe key used to avoid duplicate rows."""
    if envelope.occurred_at.tzinfo is None:
        raise TimezoneAwareRequiredError.for_occurrence()

    canonical_payload = _serialise_for_hash(
        envelope.payload, is_normalised=payload_is_normalised
    )
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
        dedupe_key = make_dedupe_key(envelope_copy, payload_is_normalised=True)

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
            except IntegrityError as exc:
                await session.rollback()
                existing = await self._load_existing(session, envelope_copy, dedupe_key)
                if existing is None:
                    raise RawEventPersistError from exc
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
