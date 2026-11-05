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
    repository = Repository(owner="org", name="repo", default_branch="main")

    assert repository.slug == "org/repo"


def test_repository_documentation_paths_default() -> None:
    repository = Repository(owner="org", name="repo", default_branch="main")

    assert repository.documentation_paths == []


def test_repository_round_trip_defaults() -> None:
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


def _catalogue_with(project: Project) -> Catalogue:
    """Build a single-project catalogue around *project*."""
    return Catalogue(version=1, programmes=[], projects=[project])


def test_project_name_at_the_storage_limit_is_accepted() -> None:
    """A name that fits the ``String(255)`` column passes validation."""
    project = Project(key="proj", name="p" * 255, components=[])

    assert validate_catalogue(_catalogue_with(project)).projects[0].name == "p" * 255


def test_project_name_over_the_storage_limit_is_rejected() -> None:
    """An over-length name must fail validation, not the database write."""
    project = Project(key="proj", name="p" * 256, components=[])

    with pytest.raises(
        CatalogueValidationError,
        match="project proj name must be at most 255 characters",
    ):
        validate_catalogue(_catalogue_with(project))


def test_component_name_over_the_storage_limit_is_rejected() -> None:
    """A component name is stored too, so it is held to the same limit."""
    project = Project(
        key="proj",
        name="Project",
        components=[Component(key="comp", name="c" * 256)],
    )

    with pytest.raises(
        CatalogueValidationError,
        match="component comp name must be at most 255 characters",
    ):
        validate_catalogue(_catalogue_with(project))


@pytest.mark.parametrize("field", ["owner", "name", "default_branch"])
def test_repository_fields_over_the_storage_limit_are_rejected(field: str) -> None:
    """Repository segments and branch names share the storage limit."""
    repository = Repository(
        owner="org",
        name="repo",
        default_branch="main",
    )
    setattr(repository, field, "x" * 256)
    project = Project(
        key="proj",
        name="Project",
        components=[Component(key="comp", name="Component", repository=repository)],
    )

    with pytest.raises(
        CatalogueValidationError,
        match=(f"component comp repository {field} must be at most 255 characters"),
    ):
        validate_catalogue(_catalogue_with(project))
