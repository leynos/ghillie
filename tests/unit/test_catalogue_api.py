"""API surface tests for ghillie.catalogue."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import msgspec
import pytest

import ghillie.catalogue as cat


def test_package_exports_available() -> None:
    """All documented catalogue exports should exist on the package."""
    expected = {
        "Catalogue",
        "CatalogueValidationError",
        "lint_catalogue",
        "load_catalogue",
        "build_catalogue_schema",
        "write_catalogue_schema",
    }

    for name in expected:
        assert hasattr(cat, name), (
            f"Expected export '{name}' not found in ghillie.catalogue"
        )


def test_example_catalogue_loads() -> None:
    """Example catalogue should lint and contain the wildside project."""
    example_path = Path("examples/wildside-catalogue.yaml")
    assert example_path.exists(), f"Example catalogue missing at {example_path}"

    catalogue = cat.lint_catalogue(example_path)

    assert catalogue.version == 1, (
        f"Expected catalogue version 1, got {catalogue.version}"
    )
    assert any(project.key == "wildside" for project in catalogue.projects), (
        "Expected a project with key 'wildside' in the example catalogue"
    )


def test_example_catalogue_json_matches_schema(tmp_path: Path) -> None:
    """Example catalogue JSON should validate against the generated schema."""
    example_path = Path("examples/wildside-catalogue.yaml")
    assert example_path.exists()

    catalogue = cat.lint_catalogue(example_path)
    schema_path = tmp_path / "schema.json"
    json_path = tmp_path / "catalogue.json"
    cat.write_catalogue_schema(schema_path)
    json_path.write_bytes(msgspec.json.encode(catalogue))

    pajv_path = shutil.which("pajv")
    if pajv_path is None:
        pytest.fail("pajv must be installed to validate the catalogue schema")

    try:
        subprocess.run(  # noqa: S603  # rationale: static pajv invocation with constant args
            [pajv_path, "-s", str(schema_path), "-d", str(json_path)],
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        message = (
            "pajv failed to validate the example catalogue "
            f"(stdout={exc.stdout!r}, stderr={exc.stderr!r})"
        )
        raise AssertionError(message) from exc
