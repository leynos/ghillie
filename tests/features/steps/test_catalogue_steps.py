"""Behavioural regression tests for catalogue linting."""
# ruff: noqa: D103

from __future__ import annotations

import shutil
import subprocess
import typing as typ
from pathlib import Path

import msgspec
import pytest
from pytest_bdd import given, scenario, then, when

from ghillie.catalogue import (
    Catalogue,
    CatalogueValidationError,
    lint_catalogue,
    write_catalogue_schema,
)


class StepContext(typ.TypedDict, total=False):
    """State shared between BDD steps in this module."""

    catalogue_path: Path
    catalogue: Catalogue
    error: str


@scenario(
    "../catalogue_ingestion.feature",
    "Example catalogue validates and retains planned components",
)
def test_catalogue_linting() -> None:
    """Behavioural regression for catalogue linting."""


@scenario(
    "../catalogue_ingestion.feature",
    "Duplicate component keys are rejected",
)
def test_duplicate_component_bdd() -> None:
    """Duplicate component keys should fail validation."""


@scenario(
    "../catalogue_ingestion.feature",
    "Invalid slug format is rejected",
)
def test_invalid_slug_bdd() -> None:
    """Invalid slug formats should fail validation."""


@pytest.fixture
def context() -> StepContext:
    return {}


def _load_catalogue_fixture(context: StepContext, path_str: str) -> Path:
    """Resolve a catalogue fixture path, assert it exists, and store it."""
    path = Path(path_str)
    assert path.exists(), f"Expected catalogue fixture at {path_str} to exist"
    context["catalogue_path"] = path
    return path


@given('the catalogue example at "examples/wildside-catalogue.yaml"')
def catalogue_example(context: StepContext) -> Path:
    return _load_catalogue_fixture(context, "examples/wildside-catalogue.yaml")


@given('the catalogue example at "tests/fixtures/catalogues/duplicate-component.yaml"')
def duplicate_catalogue_example(context: StepContext) -> Path:
    return _load_catalogue_fixture(
        context, "tests/fixtures/catalogues/duplicate-component.yaml"
    )


@given('the catalogue example at "tests/fixtures/catalogues/invalid-slug.yaml"')
def invalid_slug_catalogue_example(context: StepContext) -> Path:
    return _load_catalogue_fixture(
        context, "tests/fixtures/catalogues/invalid-slug.yaml"
    )


@when("I lint the catalogue with the built in validator")
def lint_catalogue_file(context: StepContext) -> None:
    assert "catalogue_path" in context
    catalogue_path = context["catalogue_path"]
    context["catalogue"] = lint_catalogue(catalogue_path)


@when("I lint the catalogue expecting failure")
def lint_catalogue_failure(context: StepContext) -> None:
    assert "catalogue_path" in context
    catalogue_path = context["catalogue_path"]
    with pytest.raises(CatalogueValidationError) as excinfo:
        lint_catalogue(catalogue_path)
    context["error"] = str(excinfo.value)


@then(
    'the project "wildside" exposes a planned component '
    '"wildside-ingestion" without a repository'
)
def planned_component_present(context: StepContext) -> None:
    assert "catalogue" in context
    catalogue: Catalogue = context["catalogue"]
    wildside = next(
        (project for project in catalogue.projects if project.key == "wildside"), None
    )
    assert wildside is not None, "Expected project 'wildside' not found in catalogue"
    component = next(
        (comp for comp in wildside.components if comp.key == "wildside-ingestion"),
        None,
    )

    assert component is not None, "Expected component 'wildside-ingestion' not found"

    assert component.repository is None
    assert component.lifecycle == "planned"


@then('the component "wildside-core" depends on "wildside-engine"')
def dependency_present(context: StepContext) -> None:
    assert "catalogue" in context
    catalogue: Catalogue = context["catalogue"]
    component = next(
        (
            comp
            for project in catalogue.projects
            for comp in project.components
            if comp.key == "wildside-core"
        ),
        None,
    )

    assert component is not None, "Expected component 'wildside-core' not found"

    dependencies = {edge.component for edge in component.depends_on}
    assert "wildside-engine" in dependencies


@then("the catalogue conforms to the JSON schema via pajv")
def schema_validation(context: StepContext, tmp_path: Path) -> None:
    pajv_path = shutil.which("pajv")
    if pajv_path is None:
        pytest.fail(
            "pajv must be installed for behavioural schema validation; "
            "unit tests skip this when the binary is absent"
        )

    schema_path = tmp_path / "catalogue.schema.json"
    write_catalogue_schema(schema_path)

    data_path = tmp_path / "catalogue.json"
    assert "catalogue" in context
    catalogue: Catalogue = context["catalogue"]
    data_path.write_bytes(msgspec.json.encode(catalogue))

    try:
        subprocess.run(  # noqa: S603  # rationale: static pajv invocation with constant args
            [
                pajv_path,
                "-s",
                str(schema_path),
                "-d",
                str(data_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        message = (
            f"pajv rejected the catalogue: stdout={exc.stdout}\nstderr={exc.stderr}"
        )
        raise AssertionError(message) from exc


@then('validation reports contain "duplicate component key"')
def validation_reports_duplicate(context: StepContext) -> None:
    assert "error" in context
    assert "duplicate component key" in context["error"].lower()


@then('validation reports contain "slug"')
def validation_reports_slug(context: StepContext) -> None:
    assert "error" in context
    assert "slug" in context["error"].lower()
