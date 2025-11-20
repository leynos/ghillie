"""Typed estate catalogue structures."""

from __future__ import annotations

import typing as typ

import msgspec


class Programme(msgspec.Struct, kw_only=True):
    """A programme groups related projects under a strategic umbrella."""

    key: str
    name: str
    description: str | None = None
    projects: list[str] = msgspec.field(default_factory=list)


class Repository(msgspec.Struct, kw_only=True):
    """Repository mapping and default branch information."""

    owner: str
    name: str
    default_branch: str = "main"

    @property
    def slug(self) -> str:
        """Return the GitHub-style owner/name identifier."""
        return f"{self.owner}/{self.name}"


class ComponentLink(msgspec.Struct, kw_only=True):
    """Directed edge between components."""

    component: str
    kind: typ.Literal["runtime", "dev", "test", "ops"] = "runtime"
    rationale: str | None = None


class Component(msgspec.Struct, kw_only=True):
    """Component within a project, with optional repository mapping."""

    key: str
    name: str
    type: str = "service"
    description: str | None = None
    lifecycle: typ.Literal["planned", "active", "deprecated"] = "active"
    repository: Repository | None = None
    depends_on: list[ComponentLink] = msgspec.field(default_factory=list)
    blocked_by: list[ComponentLink] = msgspec.field(default_factory=list)
    emits_events_to: list[ComponentLink] = msgspec.field(default_factory=list)
    notes: list[str] = msgspec.field(default_factory=list)


class NoiseFilters(msgspec.Struct, kw_only=True):
    """Noise control for ingestion and reporting."""

    ignore_authors: list[str] = msgspec.field(default_factory=list)
    ignore_labels: list[str] = msgspec.field(default_factory=list)
    ignore_paths: list[str] = msgspec.field(default_factory=list)
    ignore_title_prefixes: list[str] = msgspec.field(default_factory=list)


class StatusSettings(msgspec.Struct, kw_only=True):
    """Status generation preferences per project."""

    summarise_dependency_prs: bool = False
    emphasise_documentation: bool = False
    prefer_long_form: bool = False


class Project(msgspec.Struct, kw_only=True):
    """Project definition with components and configuration."""

    key: str
    name: str
    description: str | None = None
    programme: str | None = None
    components: list[Component]
    noise: NoiseFilters = msgspec.field(default_factory=NoiseFilters)
    status: StatusSettings = msgspec.field(default_factory=StatusSettings)
    documentation_paths: list[str] = msgspec.field(default_factory=list)


class Catalogue(msgspec.Struct, kw_only=True):
    """Top-level estate catalogue."""

    version: int
    projects: list[Project]
    programmes: list[Programme] = msgspec.field(default_factory=list)
