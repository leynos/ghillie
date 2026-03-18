"""Prompt templates for OpenAI status model."""

from __future__ import annotations

import typing as typ
from string.templatelib import Interpolation, Template, convert

if typ.TYPE_CHECKING:
    from ghillie.evidence.models import RepositoryEvidenceBundle

type TemplateLike = str | Template


class _NumberedItem(typ.Protocol):
    """Structural type for evidence items with a number, title and state."""

    number: int
    title: str
    state: str


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


# Python 3.14 template strings preserve interpolation structure instead of
# eagerly producing `str`. Prompt construction still needs plain text for the
# OpenAI payload, so keep the conversion explicit and local to this module.
def _render_template(template: TemplateLike) -> str:
    """Render plain text or a template string back to plain text."""
    if isinstance(template, str):
        return template

    rendered_parts: list[str] = []
    for item in template:
        if isinstance(item, str):
            rendered_parts.append(item)
            continue
        if not isinstance(item, Interpolation):
            msg = (
                "Expected template segment to be str or Interpolation, "
                f"got {type(item).__name__}"
            )
            raise TypeError(msg)
        converted_value = convert(item.value, item.conversion)
        rendered_parts.append(format(converted_value, item.format_spec))
    return "".join(rendered_parts)


def _render_lines(lines: typ.Iterable[TemplateLike]) -> list[str]:
    """Render a sequence of prompt fragments to plain text."""
    return [_render_template(line) for line in lines]


def _format_previous_reports(evidence: RepositoryEvidenceBundle) -> list[TemplateLike]:
    """Format previous reports section."""
    if not evidence.previous_reports:
        return []

    sections: list[TemplateLike] = ["", "## Previous Reports"]
    for prev in evidence.previous_reports:
        sections.append("")
        sections.append(
            t"### Report from {prev.window_start.date()} to {prev.window_end.date()}"
        )
        sections.append(t"- Status: {prev.status.value}")
        if prev.highlights:
            highlights_str = ", ".join(prev.highlights[:3])
            sections.append(t"- Highlights: {highlights_str}")
        if prev.risks:
            risks_str = ", ".join(prev.risks[:3])
            sections.append(t"- Risks: {risks_str}")
    return sections


def _format_work_type_breakdown(
    evidence: RepositoryEvidenceBundle,
) -> list[TemplateLike]:
    """Format work type breakdown section."""
    if not evidence.work_type_groupings:
        return []

    sections: list[TemplateLike] = ["", "## Work Type Breakdown"]
    for grouping in evidence.work_type_groupings:
        total = grouping.commit_count + grouping.pr_count + grouping.issue_count
        sections.append(t"- {grouping.work_type.value}: {total} items")
        sections.extend(t"  - {title}" for title in grouping.sample_titles[:2])
    return sections


def _format_numbered_items(
    heading: str,
    items: typ.Sequence[_NumberedItem],
    *,
    limit: int = 10,
) -> list[TemplateLike]:
    """Format a section of numbered items (pull requests or issues)."""
    if not items:
        return []

    sections: list[TemplateLike] = ["", heading]
    sections.extend(
        t"- #{item.number}: {item.title} [{item.state}]" for item in items[:limit]
    )
    return sections


def _format_pull_requests(evidence: RepositoryEvidenceBundle) -> list[TemplateLike]:
    """Format pull requests section."""
    return _format_numbered_items("## Pull Requests", evidence.pull_requests)


def _format_issues(evidence: RepositoryEvidenceBundle) -> list[TemplateLike]:
    """Format issues section."""
    return _format_numbered_items("## Issues", evidence.issues)


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
    sections: list[TemplateLike] = [
        t"# Repository Status Report: {evidence.repository.slug}",
        "",
        t"Reporting window: {evidence.window_start.isoformat()} to "
        t"{evidence.window_end.isoformat()}",
    ]

    # Add optional sections
    sections.extend(_format_previous_reports(evidence))

    # Activity summary
    sections.extend(
        [
            "",
            "## Activity Summary",
            t"- Commits: {len(evidence.commits)}",
            t"- Pull requests: {len(evidence.pull_requests)}",
            t"- Issues: {len(evidence.issues)}",
            t"- Documentation changes: {len(evidence.documentation_changes)}",
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

    return "\n".join(_render_lines(sections))
