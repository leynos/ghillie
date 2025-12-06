"""Gold layer metadata tables for generated reports and coverage."""

from __future__ import annotations

import datetime as dt  # noqa: TC003
import enum
import typing as typ
import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ghillie.bronze.storage import Base, UTCDateTime
from ghillie.common.time import utcnow

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from ghillie.silver.storage import EventFact, Repository


class ReportScope(enum.StrEnum):
    """Enumerate supported report scopes for Gold metadata."""

    REPOSITORY = "repository"
    PROJECT = "project"
    ESTATE = "estate"


class ReportProject(Base):
    """Lightweight dimension table for project-scoped reports."""

    __tablename__ = "report_projects"
    __table_args__ = (UniqueConstraint("key", name="uq_report_projects_key"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), default=None)
    estate_id: Mapped[str | None] = mapped_column(String(36), default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    reports: Mapped[list[Report]] = relationship(back_populates="project")


class Report(Base):
    """Metadata for generated reports stored in the Gold layer."""

    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_scope_generated_at", "scope", "generated_at"),
        Index("ix_reports_repo_id", "repository_id"),
        Index("ix_reports_project_id", "project_id"),
        CheckConstraint(
            "(scope != 'repository') OR repository_id IS NOT NULL",
            name="ck_reports_repository_scope_has_repo",
        ),
        CheckConstraint(
            "(scope != 'project') OR project_id IS NOT NULL",
            name="ck_reports_project_scope_has_project",
        ),
        CheckConstraint(
            "(window_end > window_start)",
            name="ck_reports_window_bounds",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    scope: Mapped[ReportScope] = mapped_column(
        Enum(
            ReportScope,
            native_enum=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
    )
    repository_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("repositories.id", ondelete="SET NULL"), default=None
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("report_projects.id", ondelete="SET NULL"), default=None
    )
    estate_id: Mapped[str | None] = mapped_column(String(36), default=None)
    window_start: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False)
    window_end: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False)
    generated_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False
    )
    model: Mapped[str | None] = mapped_column(String(128), default=None)
    human_text: Mapped[str | None] = mapped_column(Text(), default=None)
    machine_summary: Mapped[dict[str, typ.Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    repository: Mapped[Repository | None] = relationship(
        back_populates="reports", foreign_keys=[repository_id]
    )
    project: Mapped[ReportProject | None] = relationship(
        back_populates="reports", foreign_keys=[project_id]
    )
    coverage_records: Mapped[list[ReportCoverage]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class ReportCoverage(Base):
    """Mapping table recording which event facts feed a given report."""

    __tablename__ = "report_coverage"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "event_fact_id", name="uq_report_coverage_report_event"
        ),
        Index("ix_report_coverage_event_fact", "event_fact_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    event_fact_id: Mapped[int] = mapped_column(
        ForeignKey("event_facts.id", ondelete="CASCADE"), nullable=False
    )

    report: Mapped[Report] = relationship(back_populates="coverage_records")
    event_fact: Mapped[EventFact] = relationship()


async def init_gold_storage(engine: AsyncEngine) -> None:
    """Create Gold tables registered with the shared Base if absent."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
