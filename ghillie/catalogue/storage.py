"""Persistence models for the catalogue importer.

The importer reconciles catalogue definitions into relational tables covering
estates, projects, components, component edges, and repositories. Models keep
to portable SQLAlchemy types so the same code works with SQLite in tests and
PostgreSQL in production.
"""

from __future__ import annotations

import datetime as dt  # noqa: TC003
import typing as typ
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ghillie.common.time import utcnow

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


class Base(DeclarativeBase):
    """Base declarative class for catalogue persistence."""

    metadata: typ.Any


class Estate(Base):
    """Logical grouping of projects under management."""

    __tablename__ = "estates"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text(), default=None)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    projects: Mapped[list[ProjectRecord]] = relationship(
        back_populates="estate", cascade="all, delete-orphan"
    )


class ProjectRecord(Base):
    """Project derived from the catalogue."""

    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("estate_id", "key", name="uq_project_key"),)

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    estate_id: Mapped[str] = mapped_column(ForeignKey("estates.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text(), default=None)
    programme: Mapped[str | None] = mapped_column(String(128), default=None)
    noise: Mapped[dict[str, typ.Any]] = mapped_column(JSON, default=dict)
    status_preferences: Mapped[dict[str, typ.Any]] = mapped_column(JSON, default=dict)
    documentation_paths: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    estate: Mapped[Estate] = relationship(back_populates="projects")
    components: Mapped[list[ComponentRecord]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class RepositoryRecord(Base):
    """Repository mapped from a catalogue component."""

    __tablename__ = "catalogue_repositories"
    __table_args__ = (
        UniqueConstraint("owner", "name", name="uq_catalogue_repository_slug"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    default_branch: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    documentation_paths: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    components: Mapped[list[ComponentRecord]] = relationship(
        back_populates="repository"
    )

    @property
    def slug(self) -> str:
        """Return owner/name to match catalogue notation."""
        return f"{self.owner}/{self.name}"


class ComponentRecord(Base):
    """Component definition tied to a project."""

    __tablename__ = "components"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_component_key_per_project"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    repository_id: Mapped[str | None] = mapped_column(
        ForeignKey("catalogue_repositories.id", ondelete="SET NULL"), default=None
    )
    key: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(64))
    lifecycle: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text(), default=None)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    project: Mapped[ProjectRecord] = relationship(back_populates="components")
    repository: Mapped[RepositoryRecord | None] = relationship(
        back_populates="components"
    )
    outgoing_edges: Mapped[list[ComponentEdgeRecord]] = relationship(
        back_populates="from_component",
        cascade="all, delete-orphan",
        foreign_keys="ComponentEdgeRecord.from_component_id",
    )
    incoming_edges: Mapped[list[ComponentEdgeRecord]] = relationship(
        back_populates="to_component",
        cascade="all, delete-orphan",
        foreign_keys="ComponentEdgeRecord.to_component_id",
    )


class ComponentEdgeRecord(Base):
    """Directed relationship between components."""

    __tablename__ = "component_edges"
    __table_args__ = (
        UniqueConstraint(
            "from_component_id",
            "to_component_id",
            "relationship",
            name="uq_component_edge",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    from_component_id: Mapped[str] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), index=True
    )
    to_component_id: Mapped[str] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), index=True
    )
    relationship_type: Mapped[str] = mapped_column("relationship", String(32))
    kind: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str | None] = mapped_column(Text(), default=None)

    from_component: Mapped[ComponentRecord] = relationship(
        back_populates="outgoing_edges", foreign_keys=[from_component_id]
    )
    to_component: Mapped[ComponentRecord] = relationship(
        back_populates="incoming_edges", foreign_keys=[to_component_id]
    )


class CatalogueImportRecord(Base):
    """Audit log of processed catalogue commits per estate."""

    __tablename__ = "catalogue_imports"
    __table_args__ = (
        UniqueConstraint("estate_id", "commit_sha", name="uq_catalogue_import_commit"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    estate_id: Mapped[str] = mapped_column(ForeignKey("estates.id", ondelete="CASCADE"))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    imported_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    estate: Mapped[Estate] = relationship()


async def init_catalogue_storage(engine: AsyncEngine) -> None:
    """Create catalogue tables if they do not already exist.

    Parameters
    ----------
    engine:
        Async SQLAlchemy engine bound to the target database.

    Returns
    -------
    None

    Examples
    --------
    >>> from sqlalchemy.ext.asyncio import create_async_engine
    >>> engine = create_async_engine("sqlite+aiosqlite:///catalogue.db")
    >>> await init_catalogue_storage(engine)

    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
