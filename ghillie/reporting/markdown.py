"""Markdown renderer for repository status reports.

Transforms Gold layer report data and repository metadata into a
structured Markdown document suitable for human consumption and
version-controlled storage.

The renderer reads from ``Report.machine_summary`` (the structured dict
produced by ``to_machine_summary()``) rather than ``Report.human_text``,
guaranteeing that the rendered content matches the database exactly.

Usage
-----
Render a report as Markdown:

>>> from ghillie.reporting.markdown import render_report_markdown
>>> md = render_report_markdown(report, owner="acme", name="widget")

"""

from __future__ import annotations

import typing as typ

from ghillie.common.slug import repo_slug as _repo_slug

if typ.TYPE_CHECKING:
    import datetime as dt

    from ghillie.gold.storage import Report

_STATUS_LABELS: dict[str, str] = {
    "on_track": "On Track",
    "at_risk": "At Risk",
    "blocked": "Blocked",
    "unknown": "Unknown",
}


def _format_date(value: dt.datetime) -> str:
    """Format a datetime as an ISO date string (YYYY-MM-DD)."""
    return value.strftime("%Y-%m-%d")


def _format_generated_at(value: dt.datetime) -> str:
    """Format a datetime as a human-readable UTC timestamp."""
    return value.strftime("%Y-%m-%d %H:%M UTC")


def _render_title(
    lines: list[str],
    repo_slug: str,
    date_range: str,
) -> None:
    """Append the level-1 heading with repository slug and date range."""
    lines.append(f"# {repo_slug} — Status report ({date_range})")
    lines.append("")


def _render_status(lines: list[str], ms: dict[str, typ.Any]) -> None:
    """Append the bold status indicator line."""
    status_raw = str(ms.get("status") or "unknown")
    status_label = _STATUS_LABELS.get(status_raw, status_raw)
    lines.append(f"**Status:** {status_label}")
    lines.append("")


def _render_summary_section(lines: list[str], ms: dict[str, typ.Any]) -> None:
    """Append the summary section if present."""
    summary = ms.get("summary", "")
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(str(summary))
        lines.append("")


def _render_bullet_section(
    lines: list[str],
    heading: str,
    items: list[str],
) -> None:
    """Append a bulleted section if items are non-empty."""
    if items:
        lines.append(f"## {heading}")
        lines.append("")
        lines.extend(f"- {item}" for item in items)
        lines.append("")


def _render_metadata_footer(
    lines: list[str],
    report: Report,
    start: str,
    end: str,
) -> None:
    """Append the horizontal rule and metadata footer."""
    lines.append("---")
    lines.append("")
    generated_str = _format_generated_at(report.generated_at)
    model = report.model or "unknown"
    lines.append(
        f"*Generated at {generated_str} by {model}"
        f" | Window: {start} to {end}"
        f" | Report ID: {report.id}*"
    )
    lines.append("")


def render_report_markdown(
    report: Report,
    *,
    owner: str,
    name: str,
) -> str:
    """Render a Gold layer report as a structured Markdown document.

    Parameters
    ----------
    report
        The persisted Gold layer report record containing
        ``machine_summary``, ``human_text``, window timestamps, and model
        metadata.
    owner
        GitHub repository owner (organisation or user).
    name
        GitHub repository name.

    Returns
    -------
    str
        A complete Markdown document representing the report.

    """
    ms: dict[str, typ.Any] = report.machine_summary or {}
    lines: list[str] = []

    window_start_str = _format_date(report.window_start)
    window_end_str = _format_date(report.window_end)
    slug = _repo_slug(owner, name)
    date_range = f"{window_start_str} to {window_end_str}"

    _render_title(lines, slug, date_range)
    _render_status(lines, ms)
    _render_summary_section(lines, ms)
    _render_bullet_section(lines, "Highlights", ms.get("highlights", []))
    _render_bullet_section(lines, "Risks", ms.get("risks", []))
    _render_bullet_section(lines, "Next steps", ms.get("next_steps", []))
    _render_metadata_footer(lines, report, window_start_str, window_end_str)

    return "\n".join(lines)
