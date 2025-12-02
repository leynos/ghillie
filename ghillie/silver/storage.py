"""Silver staging models built from Bronze raw events."""

from __future__ import annotations

import datetime as dt  # noqa: TC003 - required at runtime for SQLAlchemy annotation evaluation
import typing as typ

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ghillie.bronze.storage import Base, RawEvent, UTCDateTime

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


class EventFact(Base):
    """Minimal Silver table to preserve deterministic Bronze→Silver mapping."""

    __tablename__ = "event_facts"
    __table_args__ = (
        UniqueConstraint("raw_event_id", name="uq_event_fact_raw_event"),
        Index("ix_event_facts_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_event_id: Mapped[int] = mapped_column(
        ForeignKey("raw_events.id", ondelete="CASCADE"), nullable=False
    )
    repo_external_id: Mapped[str | None] = mapped_column(String(255), default=None)
    event_type: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    payload: Mapped[dict[str, typ.Any]] = mapped_column(JSON)

    raw_event: Mapped[RawEvent] = relationship()


async def init_silver_storage(engine: AsyncEngine) -> None:
    """Create all tables registered with Base if they are absent."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
