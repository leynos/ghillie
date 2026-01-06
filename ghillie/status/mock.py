"""Mock implementation of StatusModel for testing and development."""

from __future__ import annotations

from ghillie.evidence.models import (
    ReportStatus,
    RepositoryEvidenceBundle,
    WorkType,
)
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
        if evidence.previous_reports:
            latest = evidence.previous_reports[0]
            if latest.risks and latest.status in (
                ReportStatus.AT_RISK,
                ReportStatus.BLOCKED,
            ):
                return ReportStatus.AT_RISK

        # Bug activity > feature activity → AT_RISK
        bug_count = 0
        feature_count = 0
        for grouping in evidence.work_type_groupings:
            if grouping.work_type == WorkType.BUG:
                bug_count = grouping.commit_count + grouping.pr_count
            elif grouping.work_type == WorkType.FEATURE:
                feature_count = grouping.commit_count + grouping.pr_count

        if bug_count > feature_count and bug_count > 0:
            return ReportStatus.AT_RISK

        return ReportStatus.ON_TRACK

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
            if grouping.work_type == WorkType.FEATURE and grouping.pr_count > 0:
                pr_word = "PR" if grouping.pr_count == 1 else "PRs"
                highlights.append(f"Delivered {grouping.pr_count} feature {pr_word}")
            if grouping.work_type == WorkType.DOCUMENTATION:
                total = grouping.commit_count + grouping.pr_count
                if total > 0:
                    highlights.append("Updated documentation")

        # Include sample titles from feature work
        for grouping in evidence.work_type_groupings:
            if grouping.work_type == WorkType.FEATURE:
                highlights.extend(grouping.sample_titles[:2])

        return tuple(highlights[:5])

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

        # Check for open PRs
        open_prs = [pr for pr in evidence.pull_requests if pr.state == "open"]
        if open_prs:
            pr_word = "PR" if len(open_prs) == 1 else "PRs"
            steps.append(f"Review {len(open_prs)} open {pr_word}")

        # Check for open issues
        open_issues = [i for i in evidence.issues if i.state == "open"]
        if open_issues:
            issue_word = "issue" if len(open_issues) == 1 else "issues"
            steps.append(f"Triage {len(open_issues)} open {issue_word}")

        return tuple(steps[:5])
