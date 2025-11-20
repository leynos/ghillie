"""API surface tests for ghillie.catalogue."""
# ruff: noqa: D103

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import msgspec
import pytest

import ghillie.catalogue as cat


def test_package_exports_available() -> None:
    expected = {
        "Catalogue",
        "CatalogueValidationError",
        "lint_catalogue",
        "load_catalogue",
        "build_catalogue_schema",
        "write_catalogue_schema",
    }

    for name in expected:
        assert hasattr(cat, name)


def test_example_catalogue_loads() -> None:
    example_path = Path("examples/wildside-catalogue.yaml")
    assert example_path.exists()

    catalogue = cat.lint_catalogue(example_path)

    assert catalogue.version == 1
    assert any(project.key == "wildside" for project in catalogue.projects)


def test_example_catalogue_json_matches_schema(tmp_path: Path) -> None:
    example_path = Path("examples/wildside-catalogue.yaml")
    assert example_path.exists()

    catalogue = cat.lint_catalogue(example_path)
    schema_path = tmp_path / "schema.json"
    json_path = tmp_path / "catalogue.json"
    cat.write_catalogue_schema(schema_path)
    json_path.write_bytes(msgspec.json.encode(catalogue))

    pajv_path = shutil.which("pajv")
    if pajv_path is None:
        pytest.skip("pajv not installed")

    result = subprocess.run(  # noqa: S603
        [pajv_path, "-s", str(schema_path), "-d", str(json_path)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
