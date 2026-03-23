"""Unit tests for CLI output formatting helpers."""

from __future__ import annotations

import json
import typing as typ

import pytest
import ruamel.yaml

from ghillie.cli.output import render_output


@pytest.fixture
def sample_rows() -> list[dict[str, object]]:
    """Sample data for output rendering tests."""
    return [
        {"name": "alpha", "value": 1, "enabled": True},
        {"name": "beta", "value": 2, "enabled": False},
    ]


def test_render_output_json_deterministic_key_order(
    sample_rows: list[dict[str, object]],
) -> None:
    """JSON output should be deterministic with respect to key ordering."""
    payload = typ.cast("typ.Mapping[str, object]", {"items": sample_rows})
    output = render_output(
        payload,
        output="json",
    )

    # Structural assertion
    parsed = json.loads(output)
    assert parsed == {"items": sample_rows}

    # Deterministic key order assertion
    expected = json.dumps(
        {"items": sample_rows},
        sort_keys=True,
    )
    assert output == expected


def test_render_output_yaml_structure(
    sample_rows: list[dict[str, object]],
) -> None:
    """YAML output should contain a structurally equivalent representation."""
    payload = typ.cast("typ.Mapping[str, object]", {"items": sample_rows})
    output = render_output(
        payload,
        output="yaml",
    )

    yaml = ruamel.yaml.YAML(typ="safe")
    parsed = yaml.load(output)
    assert parsed == {"items": sample_rows}


def test_render_output_table_structure() -> None:
    """Table output should contain key-value pairs."""
    payload = typ.cast("typ.Mapping[str, object]", {"name": "test", "count": 42})
    output = render_output(
        payload,
        output="table",
    )

    # Basic structural checks
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) >= 2

    # Ensure each field is present
    assert any("name" in line for line in lines)
    assert any("test" in line for line in lines)
    assert any("count" in line for line in lines)
    assert any("42" in line for line in lines)
