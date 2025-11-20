"""Unit tests for catalogue schema validation."""
# ruff: noqa: D103

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path

import pytest

from ghillie.catalogue import (
    Catalogue,
    CatalogueValidationError,
    build_catalogue_schema,
    lint_catalogue,
)


def test_lint_catalogue_rejects_unknown_component(tmp_path: Path) -> None:
    catalogue_file = tmp_path / "invalid-catalogue.yaml"
    catalogue_file.write_text(
        """
version: 1
projects:
  - key: alpha
    name: Alpha
    components:
      - key: alpha-api
        name: Alpha API
        repository:
          owner: org
          name: alpha
      - key: alpha-worker
        name: Alpha Worker
        depends_on:
          - component: missing-component
    noise:
      ignore_authors: []
      ignore_labels: []
      ignore_paths: []
    status:
      summarise_dependency_prs: false
        """,
        encoding="utf-8",
    )

    with pytest.raises(CatalogueValidationError) as excinfo:
        lint_catalogue(catalogue_file)

    assert "missing-component" in str(excinfo.value)
    assert "alpha-worker" in str(excinfo.value)


def test_yaml_loader_respects_yaml_1_2(tmp_path: Path) -> None:
    catalogue_file = tmp_path / "yaml-12.yaml"
    catalogue_file.write_text(
        """
version: 1
projects:
  - key: beta
    name: Beta
    components:
      - key: beta-api
        name: Beta API
        repository:
          owner: org
          name: beta
          default_branch: on
    noise:
      ignore_authors: []
      ignore_labels: []
      ignore_paths: []
    status:
      summarise_dependency_prs: true
        """,
        encoding="utf-8",
    )

    catalogue = lint_catalogue(catalogue_file)

    repository = catalogue.projects[0].components[0].repository
    assert repository is not None
    assert repository.default_branch == "on"


def test_generated_schema_mentions_projects() -> None:
    schema = build_catalogue_schema()

    assert isinstance(schema, dict)
    assert "$id" in schema
    catalogue_properties = schema["$defs"]["Catalogue"]["properties"]
    assert "projects" in catalogue_properties


def test_lint_catalogue_returns_catalogue(tmp_path: Path) -> None:
    catalogue_file = tmp_path / "lintable.yaml"
    catalogue_file.write_text(
        """
version: 1
projects:
  - key: gamma
    name: Gamma
    components:
      - key: gamma-api
        name: Gamma API
        repository:
          owner: org
          name: gamma
          default_branch: main
    noise:
      ignore_authors: ["bots"]
      ignore_labels: ["chore/deps"]
      ignore_paths: ["docs/generated/**"]
    status:
      summarise_dependency_prs: false
        """,
        encoding="utf-8",
    )

    catalogue = lint_catalogue(catalogue_file)

    assert isinstance(catalogue, Catalogue)
    assert catalogue.projects[0].noise.ignore_labels == ["chore/deps"]
