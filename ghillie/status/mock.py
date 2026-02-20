"""Mock implementation of StatusModel for testing and development."""

from __future__ import annotations

import typing as typ

from ghillie.evidence.models import (
    ReportStatus,
    RepositoryEvidenceBundle,
    WorkType,
    WorkTypeGrouping,
)
from ghillie.status.metrics import ModelInvocationMetrics
from ghillie.status.models import RepositoryStatusResult


class MockStatusModel:
    """Deterministic mock implementation of StatusModel.

    This implementation uses basic heuristics to generate status reports
    without calling an LLM. Useful for testing, development, and as a
    fallback when LLM APIs are unavailable.

    Heuristics
    ----------
    Status determination follows this priority order:

    1. Empty evidence bundle (no events) → UNKNOWN
    2. Previous reports with risks and AT_RISK/BLOCKED status → AT_RISK
    3. Bug activity exceeds feature activity → AT_RISK
    4. Otherwise → ON_TRACK

    Examples
    --------
    >>> import asyncio
    >>> from ghillie.status import MockStatusModel
    >>> model = MockStatusModel()
    >>> result = asyncio.run(model.summarize_repository(evidence_bundle))
    >>> result.status
    <ReportStatus.ON_TRACK: 'on_track'>

    """

    def __init__(self) -> None:
        """Initialize invocation metrics storage."""
        self._last_invocation_metrics: ModelInvocationMetrics | None = None

    @property
    def last_invocation_metrics(self) -> ModelInvocationMetrics | None:
        """Return metrics captured from the latest invocation."""
        return self._last_invocation_metrics

    async def summarize_repository(
        self,
        evidence: RepositoryEvidenceBundle,
    ) -> RepositoryStatusResult:
        """Generate a mock status report based on evidence heuristics.

        Parameters
        ----------
        evidence
            Complete evidence bundle for the repository.

        Returns
        -------
        RepositoryStatusResult
            Deterministic status report based on heuristic rules.

        """
        self._last_invocation_metrics = ModelInvocationMetrics(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        )
        status = self._determine_status(evidence)
        summary = self._generate_summary(evidence, status)
        highlights = self._extract_highlights(evidence)
        risks = self._extract_risks(evidence)
        next_steps = self._suggest_next_steps(evidence, status)

        return RepositoryStatusResult(
            summary=summary,
            status=status,
            highlights=highlights,
            risks=risks,
            next_steps=next_steps,
        )

    def _determine_status(self, evidence: RepositoryEvidenceBundle) -> ReportStatus:
        """Determine status based on evidence heuristics.

        Parameters
        ----------
        evidence
            Evidence bundle to analyze.

        Returns
        -------
        ReportStatus
            Determined status code.

        """
        # No activity → UNKNOWN
        if evidence.total_event_count == 0:
            return ReportStatus.UNKNOWN

        # Previous risks carried forward → AT_RISK
        if self._has_previous_risks(evidence):
            return ReportStatus.AT_RISK

        # Bug activity > feature activity → AT_RISK
        bug_count, feature_count = self._count_work_by_type(evidence)
        if bug_count > feature_count and bug_count > 0:
            return ReportStatus.AT_RISK

        return ReportStatus.ON_TRACK

    def _has_previous_risks(self, evidence: RepositoryEvidenceBundle) -> bool:
        """Check if previous reports indicate ongoing risks.

        Parameters
        ----------
        evidence
            Evidence bundle to check for previous risks.

        Returns
        -------
        bool
            True if the latest previous report has risks and AT_RISK/BLOCKED status.

        Notes
        -----
        This method assumes ``evidence.previous_reports`` is ordered most-recent
        first, as specified by the ``RepositoryEvidenceBundle`` contract.

        """
        if not evidence.previous_reports:
            return False
        latest = evidence.previous_reports[0]
        return bool(
            latest.risks
            and latest.status in (ReportStatus.AT_RISK, ReportStatus.BLOCKED)
        )

    def _count_work_by_type(
        self,
        evidence: RepositoryEvidenceBundle,
    ) -> tuple[int, int]:
        """Count work activity by bug and feature types.

        Parameters
        ----------
        evidence
            Evidence bundle to analyze.

        Returns
        -------
        tuple[int, int]
            A tuple of (bug_count, feature_count) representing combined
            commit, PR, and issue counts for each work type.

        """
        bug_count = 0
        feature_count = 0
        for grouping in evidence.work_type_groupings:
            if grouping.work_type == WorkType.BUG:
                bug_count += (
                    grouping.commit_count + grouping.pr_count + grouping.issue_count
                )
            elif grouping.work_type == WorkType.FEATURE:
                feature_count += (
                    grouping.commit_count + grouping.pr_count + grouping.issue_count
                )
        return bug_count, feature_count

    def _generate_summary(
        self,
        evidence: RepositoryEvidenceBundle,
        status: ReportStatus,
    ) -> str:
        """Generate a narrative summary.

        Parameters
        ----------
        evidence
            Evidence bundle for context.
        status
            Determined status code.

        Returns
        -------
        str
            Human-readable summary narrative.

        """
        repo_slug = evidence.repository.slug
        event_count = evidence.total_event_count

        if event_count == 0:
            return f"{repo_slug} had no recorded activity during this period."

        status_text = {
            ReportStatus.ON_TRACK: "is on track",
            ReportStatus.AT_RISK: "is at risk",
            ReportStatus.BLOCKED: "is blocked",
            ReportStatus.UNKNOWN: "has unknown status",
        }[status]

        commit_count = len(evidence.commits)
        pr_count = len(evidence.pull_requests)
        issue_count = len(evidence.issues)

        # Pluralize correctly
        commits_word = "commit" if commit_count == 1 else "commits"
        prs_word = "pull request" if pr_count == 1 else "pull requests"
        issues_word = "issue" if issue_count == 1 else "issues"

        return (
            f"{repo_slug} {status_text} with {event_count} events "
            f"including {commit_count} {commits_word}, "
            f"{pr_count} {prs_word}, "
            f"and {issue_count} {issues_word}."
        )

    def _extract_highlights(
        self,
        evidence: RepositoryEvidenceBundle,
    ) -> tuple[str, ...]:
        """Extract highlights from work type groupings.

        Parameters
        ----------
        evidence
            Evidence bundle to extract highlights from.

        Returns
        -------
        tuple[str, ...]
            Up to 5 highlight strings.

        """
        highlights: list[str] = []

        for grouping in evidence.work_type_groupings:
            if grouping.work_type == WorkType.FEATURE:
                self._add_feature_highlights(grouping, highlights)
            elif grouping.work_type == WorkType.DOCUMENTATION:
                self._add_documentation_highlights(grouping, highlights)

        return tuple(highlights[:5])

    def _add_feature_highlights(
        self,
        grouping: WorkTypeGrouping,
        highlights: list[str],
    ) -> None:
        """Add highlights from a FEATURE work type grouping.

        Parameters
        ----------
        grouping
            Feature work type grouping to extract highlights from.
        highlights
            List to append highlights to (modified in place).

        """
        if grouping.pr_count > 0:
            pr_word = "PR" if grouping.pr_count == 1 else "PRs"
            highlights.append(f"Delivered {grouping.pr_count} feature {pr_word}")
        highlights.extend(grouping.sample_titles[:2])

    def _add_documentation_highlights(
        self,
        grouping: WorkTypeGrouping,
        highlights: list[str],
    ) -> None:
        """Add highlights from a DOCUMENTATION work type grouping.

        Parameters
        ----------
        grouping
            Documentation work type grouping to extract highlights from.
        highlights
            List to append highlights to (modified in place).

        """
        total = grouping.commit_count + grouping.pr_count
        if total > 0:
            highlights.append("Updated documentation")

    def _extract_risks(
        self,
        evidence: RepositoryEvidenceBundle,
    ) -> tuple[str, ...]:
        """Extract or carry forward risks.

        Parameters
        ----------
        evidence
            Evidence bundle to extract risks from.

        Returns
        -------
        tuple[str, ...]
            Up to 5 risk strings.

        """
        risks: list[str] = []

        # Carry forward previous risks
        if evidence.previous_reports:
            risks.extend(
                f"(Ongoing) {risk}" for risk in evidence.previous_reports[0].risks[:2]
            )

        # Add new risks from bug activity
        for grouping in evidence.work_type_groupings:
            if grouping.work_type == WorkType.BUG and grouping.issue_count > 0:
                issue_word = "issue" if grouping.issue_count == 1 else "issues"
                risks.append(
                    f"{grouping.issue_count} bug {issue_word} require attention"
                )

        return tuple(risks[:5])

    def _suggest_next_steps(
        self,
        evidence: RepositoryEvidenceBundle,
        status: ReportStatus,
    ) -> tuple[str, ...]:
        """Suggest next steps based on status and evidence.

        Parameters
        ----------
        evidence
            Evidence bundle for context.
        status
            Current status code.

        Returns
        -------
        tuple[str, ...]
            Up to 5 suggested next step strings.

        """
        steps: list[str] = []

        if status == ReportStatus.AT_RISK:
            steps.append("Review and address identified risks")

        if status == ReportStatus.UNKNOWN:
            steps.append("Investigate lack of activity")

        # Add PR review step if open PRs exist
        self._add_open_items_step(
            items=list(evidence.pull_requests),
            names=("PR", "PRs"),
            action="Review",
            steps=steps,
        )
        # Add issue triage step if open issues exist
        self._add_open_items_step(
            items=list(evidence.issues),
            names=("issue", "issues"),
            action="Triage",
            steps=steps,
        )

        return tuple(steps[:5])

    def _add_open_items_step(
        self,
        items: list[typ.Any],
        names: tuple[str, str],
        action: str,
        steps: list[str],
    ) -> None:
        """Add a step for open items if any exist.

        Parameters
        ----------
        items
            List of items with a 'state' attribute.
        names
            Tuple of (singular, plural) forms (e.g., ("PR", "PRs")).
        action
            Action verb for the step (e.g., "Review").
        steps
            List to append step to (modified in place).

        """
        open_items = [item for item in items if item.state == "open"]
        if not open_items:
            return
        singular, plural = names
        item_word = singular if len(open_items) == 1 else plural
        steps.append(f"{action} {len(open_items)} open {item_word}")
