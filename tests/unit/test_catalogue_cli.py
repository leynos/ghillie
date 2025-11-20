"""CLI validation behaviour tests."""
# ruff: noqa: D103

from __future__ import annotations

import subprocess
import sys
from pathlib import Path  # noqa: TC003

import msgspec


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "ghillie.catalogue.cli", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )


def test_cli_valid_catalogue_outputs_schema_and_json(tmp_path: Path) -> None:
    catalogue = tmp_path / "valid.yaml"
    catalogue.write_text(
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
    noise:
      ignore_authors: []
      ignore_labels: []
      ignore_paths: []
    status:
      summarise_dependency_prs: false
        """,
        encoding="utf-8",
    )

    schema_out = tmp_path / "schema.json"
    json_out = tmp_path / "catalogue.json"

    result = _run_cli(
        [str(catalogue), "--schema-out", str(schema_out), "--json-out", str(json_out)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "is valid" in result.stdout
    assert schema_out.exists()
    assert json_out.exists()

    decoded = msgspec.json.decode(json_out.read_bytes())
    assert decoded["projects"][0]["key"] == "gamma"


def test_cli_reports_validation_errors(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        """
version: 1
projects:
  - key: bad slug!
    name: Bad
    components: []
    noise:
      ignore_authors: []
      ignore_labels: []
      ignore_paths: []
    status:
      summarise_dependency_prs: false
        """,
        encoding="utf-8",
    )

    result = _run_cli([str(invalid)], cwd=tmp_path)

    assert result.returncode == 1
    assert "Catalogue validation failed" in result.stdout
    assert "bad slug" in result.stdout.lower()
