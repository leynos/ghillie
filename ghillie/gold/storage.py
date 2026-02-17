"""Gold layer metadata tables for generated reports and coverage."""

from __future__ import annotations

import datetime as dt
import enum
import typing as typ
import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ghillie.bronze.storage import Base, UTCDateTime
from ghillie.common.time import utcnow

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    # Imported for type annotations only; relationship() uses string targets to
    # avoid circular imports between silver and gold modules.
    from ghillie.silver.storage import EventFact, Repository  # noqa: TC004


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
    # JSON payload has dynamic structure; Any is required for flexibility.
    machine_summary: Mapped[dict[str, typ.Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    model_latency_ms: Mapped[int | None] = mapped_column(
        Integer(), default=None, nullable=True
    )
    prompt_tokens: Mapped[int | None] = mapped_column(
        Integer(), default=None, nullable=True
    )
    completion_tokens: Mapped[int | None] = mapped_column(
        Integer(), default=None, nullable=True
    )
    total_tokens: Mapped[int | None] = mapped_column(
        Integer(), default=None, nullable=True
    )

    repository: Mapped[Repository | None] = relationship(
        "Repository", back_populates="reports", foreign_keys=[repository_id]
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
    event_fact: Mapped[EventFact] = relationship("EventFact")


class ValidationIssuePayload(typ.TypedDict):
    """Serialized report validation issue persisted in ``ReportReview`` JSON."""

    code: str
    message: str


class ReviewState(enum.StrEnum):
    """State of a human-review marker for a failed report generation."""

    PENDING = "pending"
    RESOLVED = "resolved"


class ReportReview(Base):
    """Human-review marker created when report validation fails after retries.

    Each row records the validation issues from the last attempt so that
    operators can inspect the failure without re-running the pipeline.
    A unique constraint on ``(repository_id, window_start, window_end)``
    prevents duplicate markers for the same reporting window.
    """

    __tablename__ = "report_reviews"
    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "window_start",
            "window_end",
            name="uq_report_reviews_repo_window",
        ),
        Index("ix_report_reviews_repo_id", "repository_id"),
        Index("ix_report_reviews_state", "state"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    repository_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    window_start: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False)
    window_end: Mapped[dt.datetime] = mapped_column(UTCDateTime(), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), default=None)
    attempt_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    # JSON list of {code, message} dicts from the last validation attempt.
    validation_issues: Mapped[list[ValidationIssuePayload]] = mapped_column(
        JSON, nullable=False
    )
    state: Mapped[ReviewState] = mapped_column(
        Enum(
            ReviewState,
            native_enum=False,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
        default=ReviewState.PENDING,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False
    )

    repository: Mapped[Repository | None] = relationship(
        "Repository", foreign_keys=[repository_id]
    )


async def init_gold_storage(engine: AsyncEngine) -> None:
    """Create all tables registered with Base if they are absent."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
