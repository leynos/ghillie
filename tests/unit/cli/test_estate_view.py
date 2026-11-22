"""Rendering of validated estate pages and import summaries."""

from __future__ import annotations

import pytest

from ghillie.cli.control_plane import ControlPlanePage
from ghillie.cli.estate_view import (
    REPOSITORY_COLUMNS,
    render_import,
    render_page,
    skipped_reason,
)


def _page() -> ControlPlanePage:
    """Return one page with a row and pagination metadata."""
    return ControlPlanePage(
        items=(
            {
                "owner": "leynos",
                "name": "wildside",
                "default_branch": "main",
                "ingestion_enabled": True,
            },
        ),
        meta={"limit": 50, "offset": 0, "has_more": False, "next_offset": None},
    )


def test_render_page_table_names_the_columns() -> None:
    """Table output carries a heading and the row's values."""
    rendered = render_page(_page(), columns=REPOSITORY_COLUMNS, output="table")

    lines = rendered.splitlines()
    assert "OWNER" in lines[0]
    assert "INGESTION" in lines[0]
    assert any("leynos" in line and "wildside" in line for line in lines)


def test_render_page_json_reprints_the_metadata() -> None:
    """Machine-readable output keeps the page metadata beside the items."""
    rendered = render_page(_page(), columns=REPOSITORY_COLUMNS, output="json")

    assert '"has_more": false' in rendered
    assert '"owner": "leynos"' in rendered


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param({"skipped": True, "skipped_reason": "same sha"}, "same sha"),
        pytest.param({"skipped": True}, "already imported"),
        pytest.param({"skipped": False}, None),
        pytest.param({}, None),
    ],
)
def test_skipped_reason_reads_the_document(
    document: dict[str, object], expected: str | None
) -> None:
    """Only a skipped import has a reason, and it falls back to the default."""
    assert skipped_reason(document) == expected


def test_render_import_announces_a_skip_in_table_mode() -> None:
    """Table output says why nothing was imported, ahead of the summary."""
    rendered = render_import(
        {"skipped": True, "skipped_reason": "same sha"},
        commit_sha="c1",
        output="table",
    )

    assert rendered.startswith("SKIPPED: commit c1 was not imported (same sha).")


def test_render_import_leaves_json_output_to_the_document() -> None:
    """JSON is a contract, so no announcement is prefixed to it."""
    rendered = render_import(
        {"skipped": True, "skipped_reason": "same sha"},
        commit_sha="c1",
        output="json",
    )

    assert rendered.startswith("{")
    assert "SKIPPED" not in rendered
