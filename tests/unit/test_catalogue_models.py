"""Unit tests for catalogue model structures."""

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
    """Check that the slug joins owner and name with a slash."""
    repository = Repository(owner="org", name="repo", default_branch="main")

    assert repository.slug == "org/repo"


def test_repository_documentation_paths_default() -> None:
    """Check that documentation_paths defaults to an empty list."""
    repository = Repository(owner="org", name="repo", default_branch="main")

    assert repository.documentation_paths == []


def test_repository_round_trip_defaults() -> None:
    """Check that a default documentation_paths survives a JSON round trip."""
    catalogue = Catalogue(
        version=1,
        programmes=[],
        projects=[
            Project(
                key="proj",
                name="Project",
                components=[
                    Component(
                        key="comp",
                        name="Component",
                        repository=Repository(owner="org", name="repo"),
                    )
                ],
            )
        ],
    )

    encoded = msgspec.json.encode(catalogue)
    decoded = msgspec.json.decode(encoded, type=Catalogue)
    repository = decoded.projects[0].components[0].repository

    assert repository is not None
    assert repository.documentation_paths == []


def test_component_defaults() -> None:
    """Check the default lifecycle, repository and depends_on of a component."""
    component = Component(key="comp", name="Component")

    assert component.lifecycle == "active"
    assert component.repository is None
    assert component.depends_on == []


def test_project_defaults() -> None:
    """Check that a project gets default noise, status and documentation paths."""
    project = Project(key="proj", name="Project", components=[])

    assert isinstance(project.noise, NoiseFilters)
    assert isinstance(project.status, StatusSettings)
    assert project.documentation_paths == []


def test_catalogue_encoding_roundtrip() -> None:
    """Check that a catalogue with nested fields survives a JSON round trip."""
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
    """Check that validate_catalogue rejects a programme with an empty name."""
    programme = Programme(key="prog", name="")
    with pytest.raises(CatalogueValidationError):
        validate_catalogue(Catalogue(version=1, programmes=[programme], projects=[]))
