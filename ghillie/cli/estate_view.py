"""How the estate noun's documents and pages are rendered.

The functions take the output format explicitly and receive a page that
:func:`ghillie.cli.control_plane.parse_page` has already validated, so nothing
here inspects the response shape or reads ambient context.
"""

from __future__ import annotations

import typing as typ

from ghillie.cli.output import Column, render_collection, render_document

if typ.TYPE_CHECKING:
    from ghillie.cli.config import OutputFormat
    from ghillie.cli.control_plane import ControlPlanePage

ESTATE_COLUMNS: tuple[Column, ...] = (
    ("key", "KEY"),
    ("name", "NAME"),
    ("description", "DESCRIPTION"),
    ("last_import.commit_sha", "COMMIT"),
    ("last_import.imported_at", "IMPORTED"),
)
"""Table columns for ``estate list``."""

REPOSITORY_COLUMNS: tuple[Column, ...] = (
    ("owner", "OWNER"),
    ("name", "NAME"),
    ("default_branch", "BRANCH"),
    ("ingestion_enabled", "INGESTION"),
)
"""Table columns for ``estate repo list``."""


def skipped_reason(document: typ.Mapping[str, object]) -> str | None:
    """Return why the server skipped the import, or ``None`` when it did not."""
    if document.get("skipped") is not True:
        return None
    return str(document.get("skipped_reason") or "already imported")


def render_import(
    document: typ.Mapping[str, object],
    *,
    commit_sha: str,
    output: OutputFormat,
) -> str:
    """Render the import document, announcing a skipped commit in table mode."""
    rendered = render_document(document, output=output)
    reason = skipped_reason(document)
    if output == "table" and reason is not None:
        return (
            f"SKIPPED: commit {commit_sha} was not imported ({reason}).\n\n{rendered}"
        )
    return rendered


def render_page(
    page: ControlPlanePage,
    *,
    columns: typ.Sequence[Column],
    output: OutputFormat,
) -> str:
    """Render a validated page of rows and its pagination metadata."""
    return render_collection(
        page.items,
        columns=columns,
        output=output,
        meta=page.meta,
    )
