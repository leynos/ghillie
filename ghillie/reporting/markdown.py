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

    # Title
    window_start_str = _format_date(report.window_start)
    window_end_str = _format_date(report.window_end)
    lines.append(
        f"# {owner}/{name} — Status report ({window_start_str} to {window_end_str})"
    )
    lines.append("")

    # Status
    status_raw = str(ms.get("status", "unknown"))
    status_label = _STATUS_LABELS.get(status_raw, status_raw)
    lines.append(f"**Status:** {status_label}")
    lines.append("")

    # Summary
    summary = ms.get("summary", "")
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(str(summary))
        lines.append("")

    # Highlights
    highlights: list[str] = ms.get("highlights", [])
    if highlights:
        lines.append("## Highlights")
        lines.append("")
        lines.extend(f"- {item}" for item in highlights)
        lines.append("")

    # Risks
    risks: list[str] = ms.get("risks", [])
    if risks:
        lines.append("## Risks")
        lines.append("")
        lines.extend(f"- {item}" for item in risks)
        lines.append("")

    # Next steps
    next_steps: list[str] = ms.get("next_steps", [])
    if next_steps:
        lines.append("## Next steps")
        lines.append("")
        lines.extend(f"- {item}" for item in next_steps)
        lines.append("")

    # Metadata footer
    lines.append("---")
    lines.append("")
    generated_str = _format_generated_at(report.generated_at)
    model = report.model or "unknown"
    lines.append(
        f"*Generated at {generated_str} by {model}"
        f" | Window: {window_start_str} to {window_end_str}"
        f" | Report ID: {report.id}*"
    )
    lines.append("")

    return "\n".join(lines)
