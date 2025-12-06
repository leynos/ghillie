"""Persistence models for the Bronze raw event store."""

from __future__ import annotations

import datetime as dt
import enum
import typing as typ

from sqlalchemy import (
    JSON,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Dialect
    from sqlalchemy.ext.asyncio import AsyncEngine

from ghillie.bronze.errors import TimezoneAwareRequiredError
from ghillie.common.time import utcnow


class RawEventState(enum.IntEnum):
    """State machine for Bronze→Silver processing."""

    PENDING = 0
    PROCESSED = 1
    FAILED = 2


class Base(DeclarativeBase):
    """Base declarative class for Bronze models."""


class UTCDateTime(TypeDecorator[dt.datetime]):
    """DateTime wrapper that round-trips UTC tzinfo even on SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: dt.datetime | None, dialect: Dialect
    ) -> dt.datetime | None:
        """Force bound datetime values to UTC with tzinfo."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise TimezoneAwareRequiredError.for_occurrence()
        return value.astimezone(dt.UTC)

    def process_result_value(
        self, value: dt.datetime | None, dialect: Dialect
    ) -> dt.datetime | None:
        """Ensure result datetimes are UTC and timezone aware."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value.astimezone(dt.UTC)


class RawEvent(Base):
    """Append-only record of an external event payload."""

    __tablename__ = "raw_events"
    __table_args__ = (
        UniqueConstraint("source_system", "dedupe_key", name="uq_raw_event_dedupe"),
        Index("ix_raw_events_transform_state", "transform_state"),
        Index("ix_raw_events_repo_time", "repo_external_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_system: Mapped[str] = mapped_column(String(32))
    source_event_id: Mapped[str | None] = mapped_column(String(255), default=None)
    event_type: Mapped[str] = mapped_column(String(64))
    repo_external_id: Mapped[str | None] = mapped_column(String(255), default=None)
    occurred_at: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    ingested_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    dedupe_key: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, typ.Any]] = mapped_column(JSON)
    transform_state: Mapped[int] = mapped_column(
        Integer, default=RawEventState.PENDING.value
    )
    transform_error: Mapped[str | None] = mapped_column(Text(), default=None)


class GithubIngestionOffset(Base):
    """Cursor tracking GitHub ingestion progress per repository."""

    __tablename__ = "github_ingestion_offsets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repo_external_id: Mapped[str] = mapped_column(String(255), unique=True)
    last_commit_cursor: Mapped[str | None] = mapped_column(String(255), default=None)
    last_issue_cursor: Mapped[str | None] = mapped_column(String(255), default=None)
    last_pr_cursor: Mapped[str | None] = mapped_column(String(255), default=None)
    updated_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )


async def init_bronze_storage(engine: AsyncEngine) -> None:
    """Create all tables registered with Base if they are absent."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
