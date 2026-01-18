"""Prompt templates for OpenAI status model."""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    from ghillie.evidence.models import RepositoryEvidenceBundle

SYSTEM_PROMPT = """\
You are a technical status reporter for software repositories. Your role is to \
analyze repository activity evidence and produce concise, accurate status reports.

## Output Requirements

You must respond with valid JSON in the following structure:

```json
{
  "status": "on_track" | "at_risk" | "blocked" | "unknown",
  "summary": "1-2 sentence narrative summary of repository status",
  "highlights": ["achievement 1", "achievement 2", ...],
  "risks": ["risk 1", "risk 2", ...],
  "next_steps": ["action 1", "action 2", ...]
}
```

## Status Determination Guidelines

- **on_track**: Normal development velocity, no blockers, healthy activity
- **at_risk**: Elevated bug activity, unresolved issues from previous reports, \
or concerning patterns
- **blocked**: Critical blockers preventing progress
- **unknown**: Insufficient evidence to determine status

## Content Guidelines

1. **Summary**: Mention the repository name. Focus on what changed since the \
previous report, not what stayed the same.

2. **Highlights**: Up to 5 key achievements. Prioritize feature delivery, \
merged PRs, and significant milestones.

3. **Risks**: Up to 5 concerns. Include ongoing risks from previous reports if \
they remain unresolved.

4. **Next steps**: Up to 5 actionable recommendations. Be specific and practical.

## Repetition Avoidance

- Do NOT repeat information that was in the previous report and hasn't changed.
- If a risk from the previous report is resolved, do not include it.
- If a risk from the previous report persists, note it as ongoing.
- Focus your summary on NEW developments in the current reporting window.
"""


def _format_previous_reports(evidence: RepositoryEvidenceBundle) -> list[str]:
    """Format previous reports section."""
    if not evidence.previous_reports:
        return []

    sections: list[str] = ["", "## Previous Reports"]
    for prev in evidence.previous_reports:
        sections.append("")
        sections.append(
            f"### Report from {prev.window_start.date()} to {prev.window_end.date()}"
        )
        sections.append(f"- Status: {prev.status.value}")
        if prev.highlights:
            highlights_str = ", ".join(prev.highlights[:3])
            sections.append(f"- Highlights: {highlights_str}")
        if prev.risks:
            risks_str = ", ".join(prev.risks[:3])
            sections.append(f"- Risks: {risks_str}")
    return sections


def _format_work_type_breakdown(evidence: RepositoryEvidenceBundle) -> list[str]:
    """Format work type breakdown section."""
    if not evidence.work_type_groupings:
        return []

    sections: list[str] = ["", "## Work Type Breakdown"]
    for grouping in evidence.work_type_groupings:
        total = grouping.commit_count + grouping.pr_count + grouping.issue_count
        sections.append(f"- {grouping.work_type.value}: {total} items")
        sections.extend(f"  - {title}" for title in grouping.sample_titles[:2])
    return sections


def _format_pull_requests(evidence: RepositoryEvidenceBundle) -> list[str]:
    """Format pull requests section."""
    if not evidence.pull_requests:
        return []

    sections: list[str] = ["", "## Pull Requests"]
    sections.extend(
        f"- #{pr.number}: {pr.title} [{pr.state}]" for pr in evidence.pull_requests[:10]
    )
    return sections


def _format_issues(evidence: RepositoryEvidenceBundle) -> list[str]:
    """Format issues section."""
    if not evidence.issues:
        return []

    sections: list[str] = ["", "## Issues"]
    sections.extend(
        f"- #{issue.number}: {issue.title} [{issue.state}]"
        for issue in evidence.issues[:10]
    )
    return sections


def build_user_prompt(evidence: RepositoryEvidenceBundle) -> str:
    """Build user prompt from evidence bundle.

    Parameters
    ----------
    evidence
        Complete evidence bundle for the repository and reporting window.

    Returns
    -------
    str
        Formatted user prompt for the LLM.

    """
    sections: list[str] = [
        f"# Repository Status Report: {evidence.repository.slug}",
        "",
        (
            f"Reporting window: {evidence.window_start.isoformat()} to "
            f"{evidence.window_end.isoformat()}"
        ),
    ]

    # Add optional sections
    sections.extend(_format_previous_reports(evidence))

    # Activity summary
    sections.extend(
        [
            "",
            "## Activity Summary",
            f"- Commits: {len(evidence.commits)}",
            f"- Pull requests: {len(evidence.pull_requests)}",
            f"- Issues: {len(evidence.issues)}",
            f"- Documentation changes: {len(evidence.documentation_changes)}",
        ]
    )

    sections.extend(_format_work_type_breakdown(evidence))
    sections.extend(_format_pull_requests(evidence))
    sections.extend(_format_issues(evidence))

    # Instructions
    sections.extend(
        [
            "",
            "## Instructions",
            (
                "Analyze the above evidence and respond with a JSON status report "
                "following the schema in the system prompt."
            ),
        ]
    )

    return "\n".join(sections)
