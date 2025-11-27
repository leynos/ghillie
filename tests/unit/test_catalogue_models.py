"""Unit tests for catalogue model structures."""
# ruff: noqa: D103

from __future__ import annotations

import msgspec
import pytest

from ghillie.catalogue import (
    Catalogue,
    CatalogueValidationError,
    Component,
    ComponentLink,
    NoiseFilters,
    Programme,
    Project,
    Repository,
    StatusSettings,
    validate_catalogue,
)


def test_repository_slug_property() -> None:
    repository = Repository(owner="org", name="repo", default_branch="main")

    assert repository.slug == "org/repo"


def test_repository_documentation_paths_default() -> None:
    repository = Repository(owner="org", name="repo", default_branch="main")

    assert repository.documentation_paths == []


def test_component_defaults() -> None:
    component = Component(key="comp", name="Component")

    assert component.lifecycle == "active"
    assert component.repository is None
    assert component.depends_on == []


def test_project_defaults() -> None:
    project = Project(key="proj", name="Project", components=[])

    assert isinstance(project.noise, NoiseFilters)
    assert isinstance(project.status, StatusSettings)
    assert project.documentation_paths == []


def test_catalogue_encoding_roundtrip() -> None:
    catalogue = Catalogue(
        version=1,
        programmes=[Programme(key="prog", name="Prog")],
        projects=[
            Project(
                key="proj",
                name="Project",
                components=[
                    Component(
                        key="comp",
                        name="Component",
                        repository=Repository(
                            owner="org",
                            name="repo",
                            documentation_paths=["docs/roadmap.md"],
                        ),
                        depends_on=[ComponentLink(component="other")],
                    )
                ],
            )
        ],
    )

    encoded = msgspec.json.encode(catalogue)
    decoded = msgspec.json.decode(encoded, type=Catalogue)

    repository = decoded.projects[0].components[0].repository

    assert repository is not None
    assert repository.documentation_paths == ["docs/roadmap.md"]
    assert decoded.projects[0].components[0].depends_on[0].component == "other"


def test_programme_requires_name() -> None:
    programme = Programme(key="prog", name="")
    with pytest.raises(CatalogueValidationError):
        validate_catalogue(Catalogue(version=1, programmes=[programme], projects=[]))
