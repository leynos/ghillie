"""Unit tests for catalogue schema validation."""
# ruff: noqa: D103

from __future__ import annotations

import shutil
import subprocess
import typing as typ

import msgspec

if typ.TYPE_CHECKING:
    from pathlib import Path

import pytest

from ghillie.catalogue import (
    Catalogue,
    CatalogueValidationError,
    build_catalogue_schema,
    lint_catalogue,
    write_catalogue_schema,
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


def test_lint_catalogue_rejects_duplicate_component_keys(tmp_path: Path) -> None:
    catalogue_file = tmp_path / "duplicate-components.yaml"
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
      - key: beta-api
        name: Beta API Duplicate
        repository:
          owner: org
          name: beta-dup
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

    message = str(excinfo.value).lower()
    assert "duplicate component key" in message
    assert "beta-api" in message


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


def test_yaml_loader_invalid_yaml_syntax(tmp_path: Path) -> None:
    catalogue_file = tmp_path / "invalid.yaml"
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
      - invalid
        """,
        encoding="utf-8",
    )

    with pytest.raises(CatalogueValidationError) as excinfo:
        lint_catalogue(catalogue_file)

    assert "failed to parse" in str(excinfo.value)


def test_yaml_loader_empty_file(tmp_path: Path) -> None:
    catalogue_file = tmp_path / "empty.yaml"
    catalogue_file.write_text("", encoding="utf-8")

    with pytest.raises(CatalogueValidationError) as excinfo:
        lint_catalogue(catalogue_file)

    assert "empty" in str(excinfo.value)


def test_generated_schema_mentions_projects() -> None:
    schema = build_catalogue_schema()

    assert isinstance(schema, dict)
    assert "$id" in schema
    catalogue_properties = schema["$defs"]["Catalogue"]["properties"]
    assert "projects" in catalogue_properties


def test_schema_id_assigned() -> None:
    schema = build_catalogue_schema()

    assert schema["$id"] == "https://ghillie.example/schemas/catalogue.json"


def test_schema_validates_simple_catalogue(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.json"
    write_catalogue_schema(schema_path)

    catalogue = Catalogue(version=1, projects=[], programmes=[])
    data_path = tmp_path / "cat.json"
    data_path.write_bytes(msgspec.json.encode(catalogue))

    pajv_path = shutil.which("pajv")
    if pajv_path is None:
        pytest.skip("pajv is not installed; skipping JSON Schema validation")

    try:
        subprocess.run(  # noqa: S603
            [pajv_path, "-s", str(schema_path), "-d", str(data_path)],
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        message = f"Schema validation failed: stdout={exc.stdout}\nstderr={exc.stderr}"
        raise AssertionError(message) from exc


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


def test_lint_catalogue_rejects_unknown_programme(tmp_path: Path) -> None:
    catalogue_file = tmp_path / "unknown-programme.yaml"
    catalogue_file.write_text(
        """
version: 1
projects:
  - key: delta
    name: Delta
    programme: missing-programme
    components:
      - key: delta-api
        name: Delta API
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

    message = str(excinfo.value)
    assert "unknown programme" in message
    assert "missing-programme" in message
