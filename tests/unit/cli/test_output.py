"""Unit tests for CLI output formatting helpers."""

from __future__ import annotations

import json
import typing as typ

import pytest
import ruamel.yaml

from ghillie.cli.control_plane import (
    ControlPlaneError,
    ControlPlaneIssue,
    ControlPlaneResponse,
)
from ghillie.cli.output import (
    render_collection,
    render_document,
    render_error,
    render_output,
)


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


@pytest.fixture
def estate_items() -> list[dict[str, object]]:
    """Two fixed estate rows for collection rendering."""
    return [
        {"key": "alpha", "name": "Alpha"},
        {"key": "a-much-longer-key", "name": "Beta"},
    ]


def test_render_collection_table_aligns_columns(
    estate_items: list[dict[str, object]],
) -> None:
    """Columns line up even when the first field is much longer."""
    output = render_collection(
        estate_items,
        columns=[("key", "KEY"), ("name", "NAME")],
        output="table",
        meta={"limit": 50, "offset": 0, "has_more": False, "next_offset": None},
    )

    lines = output.splitlines()
    assert lines[0].split() == ["KEY", "NAME"]
    name_positions = {
        line.index("Alpha" if "Alpha" in line else "Beta") for line in lines[1:3]
    }
    assert len(name_positions) == 1, "the second column must start at one offset"
    assert "has_more=false" in output
    assert "next_offset=null" in output


def test_render_collection_table_reports_an_empty_page() -> None:
    """An empty collection says so instead of printing only a header."""
    output = render_collection(
        [],
        columns=[("key", "KEY")],
        output="table",
        meta={"limit": 50, "offset": 0, "has_more": False, "next_offset": None},
    )

    assert "(no items)" in output


def test_render_collection_json_keeps_the_envelope(
    estate_items: list[dict[str, object]],
) -> None:
    """JSON output is the full document, metadata included (D7)."""
    meta = {"limit": 50, "offset": 0, "has_more": False, "next_offset": None}

    output = render_collection(
        estate_items,
        columns=[("key", "KEY")],
        output="json",
        meta=meta,
    )

    assert json.loads(output) == {**meta, "items": estate_items}


def test_render_collection_yaml_keeps_the_envelope(
    estate_items: list[dict[str, object]],
) -> None:
    """YAML output is the full document too."""
    meta = {"estate_key": "demo", "limit": 50}

    output = render_collection(
        estate_items,
        columns=[("key", "KEY")],
        output="yaml",
        meta=meta,
    )

    yaml = ruamel.yaml.YAML(typ="safe")
    assert yaml.load(output) == {**meta, "items": estate_items}


def test_render_collection_reads_dotted_fields() -> None:
    """A nested field can be a column without flattening the JSON document."""
    items = [{"key": "demo", "last_import": {"commit_sha": "c1"}}]

    output = render_collection(
        items,
        columns=[("key", "KEY"), ("last_import.commit_sha", "COMMIT")],
        output="table",
        meta={},
    )

    assert "c1" in output


def test_render_document_table_flattens_one_level() -> None:
    """Nested counts are readable without being summed into one blob."""
    payload = {
        "estate_key": "demo",
        "projects": {"created": 1, "updated": 0},
        "repositories_left_disabled": ["leynos/wildside"],
    }

    output = render_document(payload, output="table")

    assert "estate_key: demo" in output
    assert "projects.created: 1" in output
    assert "projects.updated: 0" in output
    assert 'repositories_left_disabled: ["leynos/wildside"]' in output


def test_render_document_json_is_unchanged() -> None:
    """A successful JSON document is the server contract, byte for value."""
    payload = {"estate_key": "demo", "projects": {"created": 1}}

    output = render_document(payload, output="json")

    assert json.loads(output) == payload


def _error() -> ControlPlaneError:
    return ControlPlaneError(
        "catalogue_invalid",
        "catalogue validation failed",
        hint="Fix the issues listed above and import again.",
        response=ControlPlaneResponse(
            422, (ControlPlaneIssue("catalogue_schema", "projects: 42"),)
        ),
    )


def test_render_error_table_is_readable() -> None:
    """Each field of the error contract gets its own labelled line."""
    output = render_error(_error(), output="table")

    assert "Error: catalogue validation failed" in output
    assert "Code: catalogue_invalid" in output
    assert "Status: 422" in output
    assert "Hint: Fix the issues listed above" in output
    assert "catalogue_schema: projects: 42" in output


def test_render_error_json_is_structured() -> None:
    """JSON errors use the documented ``{"error": ...}`` envelope (D7)."""
    output = render_error(_error(), output="json")

    assert json.loads(output) == {
        "error": {
            "code": "catalogue_invalid",
            "message": "catalogue validation failed",
            "hint": "Fix the issues listed above and import again.",
            "status": 422,
            "issues": [{"code": "catalogue_schema", "message": "projects: 42"}],
        }
    }


def test_render_error_yaml_is_structured() -> None:
    """YAML errors carry the same fields as JSON."""
    yaml = ruamel.yaml.YAML(typ="safe")

    parsed = yaml.load(render_error(_error(), output="yaml"))

    assert parsed["error"]["code"] == "catalogue_invalid"
    assert parsed["error"]["issues"][0]["message"] == "projects: 42"


def test_render_error_omits_absent_fields() -> None:
    """A local error has no HTTP status and no issues."""
    error = ControlPlaneError(
        "invalid_estate_key",
        "estate key is invalid",
        hint="Estate keys must match the documented pattern.",
    )

    parsed = json.loads(render_error(error, output="json"))

    assert parsed["error"] == {
        "code": "invalid_estate_key",
        "message": "estate key is invalid",
        "hint": "Estate keys must match the documented pattern.",
    }
