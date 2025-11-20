"""Validation rules for the estate catalogue."""

from __future__ import annotations

import re
import typing as typ

if typ.TYPE_CHECKING:
    from .models import (
        Catalogue,
        Component,
        ComponentLink,
        Programme,
        Project,
        Repository,
    )

SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
REPO_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class CatalogueValidationError(ValueError):
    """Raised when a catalogue instance fails structural validation."""

    def __init__(self, issues: list[str]) -> None:
        """Capture validation issues whilst preserving the aggregated message."""
        message = "\n".join(issues)
        super().__init__(message)
        self.issues = issues


def validate_catalogue(catalogue: Catalogue) -> Catalogue:
    """Validate a catalogue instance, returning it when all checks pass."""
    issues: list[str] = []
    project_index: dict[str, Project] = {}
    component_index: dict[str, tuple[str, Component]] = {}
    programme_index: dict[str, Programme] = {}

    if catalogue.version < 1:
        issues.append("catalogue.version must be >= 1")

    for programme in catalogue.programmes:
        _validate_programme(programme, programme_index, issues)

    for project in catalogue.projects:
        _validate_project(
            project,
            project_index,
            component_index,
            programme_index,
            issues,
        )

    known_components = set(component_index)
    for component_key, (project_key, component) in component_index.items():
        _validate_relationships(
            component_key, project_key, component, known_components, issues
        )

    _validate_programme_membership(catalogue.programmes, project_index, issues)

    if issues:
        raise CatalogueValidationError(issues)

    return catalogue


def _validate_programme(
    programme: Programme, programme_index: dict[str, Programme], issues: list[str]
) -> None:
    _validate_slug(programme.key, "programme.key", issues)

    if programme.key in programme_index:
        issues.append(f"duplicate programme key '{programme.key}'")
    else:
        programme_index[programme.key] = programme

    if not programme.name.strip():
        issues.append(f"programme {programme.key} is missing a name")


def _validate_project(
    project: Project,
    project_index: dict[str, Project],
    component_index: dict[str, tuple[str, Component]],
    programme_index: dict[str, Programme],
    issues: list[str],
) -> None:
    _validate_slug(project.key, "project.key", issues)

    if project.key in project_index:
        issues.append(f"duplicate project key '{project.key}'")
    else:
        project_index[project.key] = project

    if not project.name.strip():
        issues.append(f"project {project.key} is missing a name")

    if project.programme and project.programme not in programme_index:
        issues.append(
            f"project {project.key} references unknown programme '{project.programme}'"
        )

    for component in project.components:
        _validate_component(project.key, component, component_index, issues)


def _validate_component(
    project_key: str,
    component: Component,
    component_index: dict[str, tuple[str, Component]],
    issues: list[str],
) -> None:
    _validate_slug(component.key, "component.key", issues)

    if component.key in component_index:
        issues.append(
            f"duplicate component key '{component.key}' used by "
            f"projects {component_index[component.key][0]} and {project_key}"
        )
    else:
        component_index[component.key] = (project_key, component)

    if not component.name.strip():
        issues.append(f"component {component.key} is missing a name")

    if component.repository is not None:
        _validate_repository(component.key, component.repository, issues)


def _validate_repository(
    component_key: str, repository: Repository, issues: list[str]
) -> None:
    for field_name, value in ("owner", repository.owner), ("name", repository.name):
        if not REPO_SEGMENT_PATTERN.match(value):
            issues.append(
                f"component {component_key} repository {field_name} '{value}' "
                "must contain only letters, digits, dots, underscores, or dashes"
            )

    if not repository.default_branch.strip():
        issues.append(
            f"component {component_key} repository default_branch must not be empty"
        )


def _validate_relationships(
    component_key: str,
    project_key: str,
    component: Component,
    known_components: set[str],
    issues: list[str],
) -> None:
    for edge_list_name, edges in (
        ("depends_on", component.depends_on),
        ("blocked_by", component.blocked_by),
        ("emits_events_to", component.emits_events_to),
    ):
        for edge in edges:
            _validate_edge(
                component_key,
                project_key,
                edge_list_name,
                edge,
                known_components,
                issues,
            )


def _validate_edge(
    component_key: str,
    project_key: str,
    edge_name: str,
    edge: ComponentLink,
    known_components: set[str],
    issues: list[str],
) -> None:
    if edge.component == component_key:
        message = (
            f"component {component_key} in project {project_key} cannot reference "
            f"itself via {edge_name}"
        )
        issues.append(message)

    if edge.component not in known_components:
        message = (
            f"component {component_key} in project {project_key} references missing "
            f"component '{edge.component}' via {edge_name}"
        )
        issues.append(message)


def _validate_programme_membership(
    programmes: list[Programme],
    project_index: dict[str, Project],
    issues: list[str],
) -> None:
    for programme in programmes:
        missing_projects = [
            project_key
            for project_key in programme.projects
            if project_key not in project_index
        ]
        issues.extend(
            f"programme {programme.key} references unknown project '{project_key}'"
            for project_key in missing_projects
        )


def _validate_slug(value: str, label: str, issues: list[str]) -> None:
    if not SLUG_PATTERN.match(value):
        issues.append(
            f"{label} '{value}' must match {SLUG_PATTERN.pattern} "
            "(lowercase slug with dashes)"
        )
