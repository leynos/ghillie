"""Silver staging and entity models built from Bronze raw events."""

from __future__ import annotations

import datetime as dt  # noqa: TC003
import typing as typ
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ghillie.bronze.storage import Base, RawEvent, UTCDateTime
from ghillie.common.time import utcnow

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from ghillie.gold.storage import Report


class Repository(Base):
    """Managed GitHub repository within the estate."""

    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint(
            "github_owner", "github_name", name="uq_repositories_owner_name"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    estate_id: Mapped[str | None] = mapped_column(String(36), default=None)
    github_owner: Mapped[str] = mapped_column(String(255))
    github_name: Mapped[str] = mapped_column(String(255))
    default_branch: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow
    )

    commits: Mapped[list[Commit]] = relationship(back_populates="repository")
    pull_requests: Mapped[list[PullRequest]] = relationship(back_populates="repository")
    issues: Mapped[list[Issue]] = relationship(back_populates="repository")
    documentation_changes: Mapped[list[DocumentationChange]] = relationship(
        back_populates="repository"
    )
    reports: Mapped[list[Report]] = relationship(back_populates="repository")


class Commit(Base):
    """Git commit captured from GitHub."""

    __tablename__ = "commits"
    __table_args__ = (Index("ix_commits_repo_time", "repo_id", "committed_at"),)

    sha: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    author_email: Mapped[str | None] = mapped_column(String(320), default=None)
    author_name: Mapped[str | None] = mapped_column(String(255), default=None)
    authored_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    committed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    message: Mapped[str | None] = mapped_column(String, default=None)
    metadata_: Mapped[dict[str, typ.Any]] = mapped_column(
        "metadata", JSON, default=dict
    )
    first_seen_at: Mapped[dt.datetime] = mapped_column(UTCDateTime(), default=utcnow)

    repository: Mapped[Repository] = relationship(back_populates="commits")
    documentation_changes: Mapped[list[DocumentationChange]] = relationship(
        back_populates="commit"
    )


class PullRequest(Base):
    """Pull request state captured from GitHub."""

    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint("repo_id", "number", name="uq_pull_requests_repo_number"),
        Index("ix_pull_requests_repo_state", "repo_id", "state"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    repo_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int]
    title: Mapped[str]
    author_login: Mapped[str | None] = mapped_column(String(255), default=None)
    state: Mapped[str]
    merged_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    closed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    base_branch: Mapped[str]
    head_branch: Mapped[str]
    metadata_: Mapped[dict[str, typ.Any]] = mapped_column(
        "metadata", JSON, default=dict
    )

    repository: Mapped[Repository] = relationship(back_populates="pull_requests")


class Issue(Base):
    """Issue state captured from GitHub."""

    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("repo_id", "number", name="uq_issues_repo_number"),
        Index("ix_issues_repo_state", "repo_id", "state"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    repo_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int]
    title: Mapped[str]
    author_login: Mapped[str | None] = mapped_column(String(255), default=None)
    state: Mapped[str]
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime())
    closed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime())
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_: Mapped[dict[str, typ.Any]] = mapped_column(
        "metadata", JSON, default=dict
    )

    repository: Mapped[Repository] = relationship(back_populates="issues")


class DocumentationChange(Base):
    """Documentation path changes derived from commits."""

    __tablename__ = "documentation_changes"
    __table_args__ = (
        UniqueConstraint(
            "repo_id",
            "commit_sha",
            "path",
            name="uq_documentation_changes_commit_path",
        ),
        Index("ix_documentation_changes_repo_time", "repo_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False
    )
    commit_sha: Mapped[str] = mapped_column(
        ForeignKey("commits.sha", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(String(512))
    change_type: Mapped[str] = mapped_column(String(32))
    is_roadmap: Mapped[bool] = mapped_column(Boolean, default=False)
    is_adr: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_: Mapped[dict[str, typ.Any]] = mapped_column(
        "metadata", JSON, default=dict
    )
    occurred_at: Mapped[dt.datetime] = mapped_column(UTCDateTime())

    repository: Mapped[Repository] = relationship(
        back_populates="documentation_changes"
    )
    commit: Mapped[Commit] = relationship(back_populates="documentation_changes")


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
