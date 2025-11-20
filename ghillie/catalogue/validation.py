"""Validation rules for the estate catalogue."""

from __future__ import annotations

import dataclasses
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


@dataclasses.dataclass(slots=True)
class ValidationState:
    """Mutable validation context shared across helper functions."""

    project_index: dict[str, Project]
    component_index: dict[str, tuple[str, Component]]
    programme_index: dict[str, Programme]
    issues: list[str]
    known_components: set[str] | None = None


class EdgeContext(typ.NamedTuple):
    """Context for validating a single component edge."""

    component_key: str
    project_key: str
    known_components: set[str]
    issues: list[str]


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
    state = ValidationState(
        project_index={},
        component_index={},
        programme_index={},
        issues=[],
    )

    if catalogue.version < 1:
        state.issues.append("catalogue.version must be >= 1")

    for programme in catalogue.programmes:
        _validate_programme(programme, state)

    for project in catalogue.projects:
        _validate_project(project, state)

    state.known_components = set(state.component_index)
    for component_key, (project_key, component) in state.component_index.items():
        _validate_relationships(component_key, project_key, component, state)

    _validate_programme_membership(
        catalogue.programmes, state.project_index, state.issues
    )

    if state.issues:
        raise CatalogueValidationError(state.issues)

    return catalogue


def _validate_programme(programme: Programme, state: ValidationState) -> None:
    _validate_slug(programme.key, "programme.key", state.issues)

    if programme.key in state.programme_index:
        state.issues.append(f"duplicate programme key '{programme.key}'")
    else:
        state.programme_index[programme.key] = programme

    if not programme.name.strip():
        state.issues.append(f"programme {programme.key} is missing a name")


def _validate_project(
    project: Project,
    state: ValidationState,
) -> None:
    _validate_slug(project.key, "project.key", state.issues)

    if project.key in state.project_index:
        state.issues.append(f"duplicate project key '{project.key}'")
    else:
        state.project_index[project.key] = project

    if not project.name.strip():
        state.issues.append(f"project {project.key} is missing a name")

    if project.programme and project.programme not in state.programme_index:
        state.issues.append(
            f"project {project.key} references unknown programme '{project.programme}'"
        )

    for component in project.components:
        _validate_component(project.key, component, state)


def _validate_component(
    project_key: str,
    component: Component,
    state: ValidationState,
) -> None:
    _validate_slug(component.key, "component.key", state.issues)

    if component.key in state.component_index:
        state.issues.append(
            f"duplicate component key '{component.key}' used by "
            f"projects {state.component_index[component.key][0]} and {project_key}"
        )
    else:
        state.component_index[component.key] = (project_key, component)

    if not component.name.strip():
        state.issues.append(f"component {component.key} is missing a name")

    if component.repository is not None:
        _validate_repository(component.key, component.repository, state.issues)


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
    state: ValidationState,
) -> None:
    if state.known_components is None:
        message = (
            "internal error: known_components not set before relationship validation"
        )
        raise RuntimeError(message)

    for edge_list_name, edges in (
        ("depends_on", component.depends_on),
        ("blocked_by", component.blocked_by),
        ("emits_events_to", component.emits_events_to),
    ):
        context = EdgeContext(
            component_key=component_key,
            project_key=project_key,
            known_components=state.known_components,
            issues=state.issues,
        )
        for edge in edges:
            _validate_edge(context, edge_list_name, edge)


def _validate_edge(context: EdgeContext, edge_name: str, edge: ComponentLink) -> None:
    if edge.component == context.component_key:
        message = (
            f"component {context.component_key} in project {context.project_key} "
            f"cannot reference itself via {edge_name}"
        )
        context.issues.append(message)

    if edge.component not in context.known_components:
        message = (
            f"component {context.component_key} in project {context.project_key} "
            f"references missing component '{edge.component}' via {edge_name}"
        )
        context.issues.append(message)


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
