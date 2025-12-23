"""Typed estate catalogue structures."""

from __future__ import annotations

import typing as typ

import msgspec


class Programme(msgspec.Struct, kw_only=True):
    """Programme groups related projects.

    Attributes
    ----------
    key : str
        Lowercase slug identifier for the programme.
    name : str
        Human-readable programme name.
    description : str, optional
        Optional narrative about the programme intent.
    projects : list[str]
        Project keys that belong to this programme.

    """

    key: str
    name: str
    description: str | None = None
    projects: list[str] = msgspec.field(default_factory=list)


class Repository(msgspec.Struct, kw_only=True):
    """Repository mapping and default branch information.

    Attributes
    ----------
    owner : str
        GitHub owner or organisation.
    name : str
        Repository name.
    default_branch : str
        Default branch name used for ingestion and status reporting.
    documentation_paths : list[str]
        Repository-specific documentation locations to track (roadmaps, ADRs).

    """

    owner: str
    name: str
    default_branch: str = "main"
    documentation_paths: list[str] = msgspec.field(default_factory=list)

    @property
    def slug(self) -> str:
        """Return the GitHub-style owner/name identifier."""
        return f"{self.owner}/{self.name}"


class ComponentLink(msgspec.Struct, kw_only=True):
    """Directed edge between components.

    Attributes
    ----------
    component : str
        Target component key.
    kind : Literal["runtime", "dev", "test", "ops"]
        Relationship type for the edge.
    rationale : str, optional
        Optional explanation of the dependency.

    """

    component: str
    kind: typ.Literal["runtime", "dev", "test", "ops"] = "runtime"
    rationale: str | None = None


class Component(msgspec.Struct, kw_only=True):
    """Component within a project, with optional repository mapping.

    Attributes
    ----------
    key : str
        Lowercase slug identifying the component.
    name : str
        Human-readable component name.
    type : Literal[
        "service", "ui", "library", "data-pipeline", "job", "tooling", "other"
    ]
        Component classification.
    description : str, optional
        Optional description of the component's purpose.
    lifecycle : Literal["planned", "active", "deprecated"]
        Current stage of the component.
    repository : Repository, optional
        GitHub repository mapping when the component has code.
    depends_on : list[ComponentLink]
        Downstream dependencies required at runtime or during development.
    blocked_by : list[ComponentLink]
        Dependencies that currently block progress.
    emits_events_to : list[ComponentLink]
        Components that consume events emitted by this component.
    notes : list[str]
        Free-form notes preserved for downstream consumers.

    """

    key: str
    name: str
    type: typ.Literal[
        "service",
        "ui",
        "library",
        "data-pipeline",
        "job",
        "tooling",
        "other",
    ] = "service"
    description: str | None = None
    lifecycle: typ.Literal["planned", "active", "deprecated"] = "active"
    repository: Repository | None = None
    depends_on: list[ComponentLink] = msgspec.field(default_factory=list)
    blocked_by: list[ComponentLink] = msgspec.field(default_factory=list)
    emits_events_to: list[ComponentLink] = msgspec.field(default_factory=list)
    notes: list[str] = msgspec.field(default_factory=list)


class NoiseFilterToggles(msgspec.Struct, kw_only=True):
    """Enable/disable individual noise filters for a project."""

    ignore_authors: bool = True
    ignore_labels: bool = True
    ignore_paths: bool = True
    ignore_title_prefixes: bool = True


class NoiseFilters(msgspec.Struct, kw_only=True):
    """Noise control for ingestion and reporting.

    Attributes
    ----------
    enabled
        Global toggle for all noise filters on this project.
    toggles
        Per-filter toggles, allowing specific filters to be enabled or disabled
        without removing their configured values.
    ignore_authors
        Authors whose commits/issues/PRs should be skipped.
    ignore_labels
        Labels that should suppress events.
    ignore_paths
        Path globs for files to ignore.
    ignore_title_prefixes
        Title prefixes whose events should be skipped.

    """

    enabled: bool = True
    toggles: NoiseFilterToggles = msgspec.field(default_factory=NoiseFilterToggles)
    ignore_authors: list[str] = msgspec.field(default_factory=list)
    ignore_labels: list[str] = msgspec.field(default_factory=list)
    ignore_paths: list[str] = msgspec.field(default_factory=list)
    ignore_title_prefixes: list[str] = msgspec.field(default_factory=list)


class StatusSettings(msgspec.Struct, kw_only=True):
    """Status generation preferences per project.

    Attributes
    ----------
    summarise_dependency_prs
        Whether to include dependency PRs in summaries.
    emphasise_documentation
        Whether to highlight documentation changes.
    prefer_long_form
        Whether to generate longer-form status text.

    """

    summarise_dependency_prs: bool = False
    emphasise_documentation: bool = False
    prefer_long_form: bool = False


class Project(msgspec.Struct, kw_only=True):
    """Project definition with components and configuration.

    Attributes
    ----------
    key
        Project slug.
    name
        Human-readable project name.
    description
        Optional description.
    programme
        Optional programme key if the project rolls up to a programme.
    components
        Component definitions for the project.
    noise
        Noise filters that apply to this project.
    status
        Status generation preferences for this project.
    documentation_paths
        Paths to roadmap/ADR/design docs relevant to the project.

    """

    key: str
    name: str
    description: str | None = None
    programme: str | None = None
    components: list[Component]
    noise: NoiseFilters = msgspec.field(default_factory=NoiseFilters)
    status: StatusSettings = msgspec.field(default_factory=StatusSettings)
    documentation_paths: list[str] = msgspec.field(default_factory=list)


class Catalogue(msgspec.Struct, kw_only=True):
    """Top-level estate catalogue.

    Attributes
    ----------
    version
        Schema version number for the catalogue file.

    projects
        Managed projects in the estate.
    programmes
        Optional programmes that group projects.

    """

    version: int
    projects: list[Project]
    programmes: list[Programme] = msgspec.field(default_factory=list)
