"""Status model output structures for repository summarization."""

from __future__ import annotations

import typing as typ

import msgspec

from ghillie.evidence.models import ReportStatus  # noqa: TC001


class RepositoryStatusResult(msgspec.Struct, kw_only=True, frozen=True):
    """Result of summarizing a repository evidence bundle.

    This structure captures the output of an LLM-based or heuristic-based
    status generation for a repository reporting window. It maps directly
    to the `Report.machine_summary` JSON column in the Gold layer.

    Attributes
    ----------
    summary
        Narrative summary of the repository's status during the window.
    status
        High-level status code (on_track, at_risk, blocked, unknown).
    highlights
        Key achievements and progress highlights (up to 5 items).
    risks
        Identified risks and concerns (up to 5 items).
    next_steps
        Suggested actions for the next period (up to 5 items).

    """

    summary: str
    status: ReportStatus
    highlights: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()


def to_machine_summary(result: RepositoryStatusResult) -> dict[str, typ.Any]:
    """Convert a RepositoryStatusResult to dict for Report.machine_summary.

    Parameters
    ----------
    result
        The status result to convert.

    Returns
    -------
    dict[str, Any]
        Dict with summary, status (as string value), highlights, risks,
        and next_steps as lists (for JSON compatibility).

    """
    return {
        "summary": result.summary,
        "status": result.status.value,
        "highlights": list(result.highlights),
        "risks": list(result.risks),
        "next_steps": list(result.next_steps),
    }
