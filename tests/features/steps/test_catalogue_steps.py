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

from ghillie.catalogue import Catalogue, lint_catalogue, write_catalogue_schema


class StepContext(typ.TypedDict, total=False):
    """State shared between BDD steps in this module."""

    catalogue_path: Path
    catalogue: Catalogue


@scenario(
    "../catalogue_ingestion.feature",
    "Example catalogue validates and retains planned components",
)
def test_catalogue_linting() -> None:
    """Behavioural regression for catalogue linting."""


@pytest.fixture
def context() -> StepContext:
    return {}


@given('the catalogue example at "examples/wildside-catalogue.yaml"')
def catalogue_example(context: StepContext) -> Path:
    path = Path("examples/wildside-catalogue.yaml")
    assert path.exists(), "Expected example catalogue to exist"
    context["catalogue_path"] = path
    return path


@when("I lint the catalogue with the built in validator")
def lint_catalogue_file(context: StepContext) -> None:
    assert "catalogue_path" in context
    catalogue_path = context["catalogue_path"]
    context["catalogue"] = lint_catalogue(catalogue_path)


@then(
    'the project "wildside" exposes a planned component '
    '"wildside-ingestion" without a repository'
)
def planned_component_present(context: StepContext) -> None:
    assert "catalogue" in context
    catalogue: Catalogue = context["catalogue"]
    wildside = next(
        project for project in catalogue.projects if project.key == "wildside"
    )
    component = next(
        comp for comp in wildside.components if comp.key == "wildside-ingestion"
    )

    assert component.repository is None
    assert component.lifecycle == "planned"


@then('the component "wildside-core" depends on "wildside-engine"')
def dependency_present(context: StepContext) -> None:
    assert "catalogue" in context
    catalogue: Catalogue = context["catalogue"]
    component = next(
        comp
        for project in catalogue.projects
        for comp in project.components
        if comp.key == "wildside-core"
    )

    dependencies = {edge.component for edge in component.depends_on}
    assert "wildside-engine" in dependencies


@then("the catalogue conforms to the JSON schema via pajv")
def schema_validation(context: StepContext, tmp_path: Path) -> None:
    pajv_path = shutil.which("pajv")
    if pajv_path is None:
        pytest.fail("pajv must be installed to validate the catalogue schema")

    schema_path = tmp_path / "catalogue.schema.json"
    write_catalogue_schema(schema_path)

    data_path = tmp_path / "catalogue.json"
    assert "catalogue" in context
    catalogue: Catalogue = context["catalogue"]
    data_path.write_bytes(msgspec.json.encode(catalogue))

    try:
        subprocess.run(  # noqa: S603 - command and args are static
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
