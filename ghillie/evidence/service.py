"""Evidence bundle generation service."""

from __future__ import annotations

import datetime as dt  # noqa: TC003
import typing as typ

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from ghillie.common.time import utcnow
from ghillie.gold.storage import Report, ReportScope
from ghillie.silver.storage import (
    Commit,
    DocumentationChange,
    EventFact,
    Issue,
    PullRequest,
    Repository,
)

from .classification import (
    DEFAULT_CLASSIFICATION_CONFIG,
    ClassificationConfig,
    classify_commit,
    classify_issue,
    classify_pull_request,
    is_merge_commit,
)
from .models import (
    CommitEvidence,
    DocumentationEvidence,
    IssueEvidence,
    PreviousReportSummary,
    PullRequestEvidence,
    ReportStatus,
    RepositoryEvidenceBundle,
    RepositoryMetadata,
    WorkType,
    WorkTypeGrouping,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from sqlalchemy.sql import ColumnElement

T = typ.TypeVar("T")


class EvidenceBundleService:
    """Generates evidence bundles for repository status reporting.

    This service queries the Silver layer to construct evidence bundles
    that aggregate all activity within a reporting window, ready for
    LLM summarisation.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        classification_config: ClassificationConfig | None = None,
        max_previous_reports: int = 2,
    ) -> None:
        """Configure the service with a session factory.

        Parameters
        ----------
        session_factory
            Async session factory for database access.
        classification_config
            Optional custom classification rules.
        max_previous_reports
            Maximum number of previous reports to include (default 2).

        """
        self._session_factory = session_factory
        self._classification_config = (
            classification_config or DEFAULT_CLASSIFICATION_CONFIG
        )
        self._max_previous_reports = max_previous_reports

    async def _fetch_entities_in_window(  # noqa: PLR0913
        self,
        session: AsyncSession,
        model: type[T],
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
        time_field: ColumnElement[dt.datetime],
        repo_field: ColumnElement[str] | None = None,
        order_by: ColumnElement[dt.datetime] | None = None,
        additional_filters: ColumnElement[bool] | None = None,
    ) -> list[T]:
        """Fetch entities within a time window.

        Parameters
        ----------
        session
            Database session.
        model
            SQLAlchemy model class to query.
        repository_id
            The repository ID to filter by.
        window_start
            Start of the window (inclusive).
        window_end
            End of the window (exclusive).
        time_field
            Column to use for time filtering.
        repo_field
            Column to use for repository filtering (defaults to model.repo_id).
        order_by
            Column to order by (defaults to time_field descending).
        additional_filters
            Optional additional filter conditions.

        Returns
        -------
        list[T]
            List of matching entities.

        """
        if repo_field is None:
            repo_field = model.repo_id  # type: ignore[attr-defined]
        if order_by is None:
            order_by = time_field.desc()

        conditions = [
            repo_field == repository_id,
            time_field >= window_start,
            time_field < window_end,
        ]
        if additional_filters is not None:
            conditions.append(additional_filters)

        stmt = select(model).where(*conditions).order_by(order_by)
        return list((await session.scalars(stmt)).all())

    def _build_classified_evidence(
        self,
        entities: list[T],
        builder: typ.Callable[[T], typ.Any],
    ) -> list[typ.Any]:
        """Build evidence list by applying a builder function to each entity.

        Parameters
        ----------
        entities
            List of ORM entities to convert.
        builder
            Function that converts an entity to an evidence struct.

        Returns
        -------
        list
            List of evidence structs.

        """
        return [builder(entity) for entity in entities]

    async def build_bundle(
        self,
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> RepositoryEvidenceBundle:
        """Build an evidence bundle for a repository and time window.

        Parameters
        ----------
        repository_id
            The Silver layer repository ID.
        window_start
            Start of the reporting window (inclusive).
        window_end
            End of the reporting window (exclusive).

        Returns
        -------
        RepositoryEvidenceBundle
            Complete evidence for status generation.

        Raises
        ------
        ValueError
            If the repository is not found.

        """
        async with self._session_factory() as session:
            # Fetch repository metadata
            repo = await self._fetch_repository(session, repository_id)
            if repo is None:
                msg = f"Repository not found: {repository_id}"
                raise ValueError(msg)

            repo_metadata = self._build_repository_metadata(repo)

            # Fetch previous reports
            previous_reports = await self._fetch_previous_reports(
                session, repository_id, window_start
            )

            # Fetch events within window
            commits = await self._fetch_commits(
                session, repository_id, window_start, window_end
            )
            prs = await self._fetch_pull_requests(
                session, repository_id, window_start, window_end
            )
            issues = await self._fetch_issues(
                session, repository_id, window_start, window_end
            )
            doc_changes = await self._fetch_documentation_changes(
                session, repository_id, window_start, window_end
            )

            # Collect event fact IDs for coverage tracking
            event_fact_ids = await self._fetch_event_fact_ids(
                session, repo.slug, window_start, window_end
            )

            # Build evidence tuples with classification
            commit_evidence = self._build_commit_evidence(commits)
            pr_evidence = self._build_pr_evidence(prs)
            issue_evidence = self._build_issue_evidence(issues)
            doc_evidence = self._build_doc_evidence(doc_changes)

            # Compute work type groupings
            groupings = self._compute_work_type_groupings(
                commit_evidence, pr_evidence, issue_evidence
            )

            return RepositoryEvidenceBundle(
                repository=repo_metadata,
                window_start=window_start,
                window_end=window_end,
                previous_reports=tuple(previous_reports),
                commits=tuple(commit_evidence),
                pull_requests=tuple(pr_evidence),
                issues=tuple(issue_evidence),
                documentation_changes=tuple(doc_evidence),
                work_type_groupings=tuple(groupings),
                event_fact_ids=tuple(event_fact_ids),
                generated_at=utcnow(),
            )

    async def _fetch_repository(
        self, session: AsyncSession, repository_id: str
    ) -> Repository | None:
        """Fetch repository by ID."""
        return await session.get(Repository, repository_id)

    def _build_repository_metadata(self, repo: Repository) -> RepositoryMetadata:
        """Convert Repository ORM model to RepositoryMetadata struct."""
        return RepositoryMetadata(
            id=repo.id,
            owner=repo.github_owner,
            name=repo.github_name,
            default_branch=repo.default_branch,
            estate_id=repo.estate_id,
            documentation_paths=tuple(repo.documentation_paths),
        )

    async def _fetch_previous_reports(
        self,
        session: AsyncSession,
        repository_id: str,
        before: dt.datetime,
    ) -> list[PreviousReportSummary]:
        """Fetch previous reports for context."""
        stmt = (
            select(Report)
            .where(
                Report.scope == ReportScope.REPOSITORY,
                Report.repository_id == repository_id,
                Report.window_end <= before,
            )
            .order_by(Report.window_end.desc())
            .limit(self._max_previous_reports)
            .options(selectinload(Report.coverage_records))
        )

        reports = (await session.scalars(stmt)).all()

        summaries = []
        for report in reports:
            summary = report.machine_summary or {}
            status = self._parse_status(summary.get("status"))
            highlights = tuple(summary.get("highlights", []))
            risks = tuple(summary.get("risks", []))

            summaries.append(
                PreviousReportSummary(
                    report_id=report.id,
                    window_start=report.window_start,
                    window_end=report.window_end,
                    status=status,
                    highlights=highlights,
                    risks=risks,
                    event_count=len(report.coverage_records),
                )
            )

        return summaries

    def _parse_status(self, status: typ.Any) -> ReportStatus:  # noqa: ANN401
        """Parse status string into ReportStatus enum."""
        if status is None:
            return ReportStatus.UNKNOWN
        status_str = str(status).lower()
        try:
            return ReportStatus(status_str)
        except ValueError:
            return ReportStatus.UNKNOWN

    async def _fetch_commits(
        self,
        session: AsyncSession,
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> list[Commit]:
        """Fetch commits within the window."""
        return await self._fetch_entities_in_window(
            session,
            Commit,
            repository_id,
            window_start,
            window_end,
            time_field=Commit.committed_at,
        )

    async def _fetch_pull_requests(
        self,
        session: AsyncSession,
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> list[PullRequest]:
        """Fetch PRs created, merged, or closed within the window."""
        stmt = (
            select(PullRequest)
            .where(
                PullRequest.repo_id == repository_id,
                # Include PRs created, merged, or closed in window
                or_(
                    (PullRequest.created_at >= window_start)
                    & (PullRequest.created_at < window_end),
                    (PullRequest.merged_at >= window_start)
                    & (PullRequest.merged_at < window_end),
                    (PullRequest.closed_at >= window_start)
                    & (PullRequest.closed_at < window_end),
                ),
            )
            .order_by(PullRequest.created_at.desc())
        )
        return list((await session.scalars(stmt)).all())

    async def _fetch_issues(
        self,
        session: AsyncSession,
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> list[Issue]:
        """Fetch issues created or closed within the window."""
        stmt = (
            select(Issue)
            .where(
                Issue.repo_id == repository_id,
                or_(
                    (Issue.created_at >= window_start)
                    & (Issue.created_at < window_end),
                    (Issue.closed_at >= window_start) & (Issue.closed_at < window_end),
                ),
            )
            .order_by(Issue.created_at.desc())
        )
        return list((await session.scalars(stmt)).all())

    async def _fetch_documentation_changes(
        self,
        session: AsyncSession,
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> list[DocumentationChange]:
        """Fetch documentation changes within the window."""
        return await self._fetch_entities_in_window(
            session,
            DocumentationChange,
            repository_id,
            window_start,
            window_end,
            time_field=DocumentationChange.occurred_at,
        )

    async def _fetch_event_fact_ids(
        self,
        session: AsyncSession,
        repo_external_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> list[int]:
        """Fetch EventFact IDs for coverage tracking."""
        stmt = select(EventFact.id).where(
            EventFact.repo_external_id == repo_external_id,
            EventFact.occurred_at >= window_start,
            EventFact.occurred_at < window_end,
        )
        return list((await session.scalars(stmt)).all())

    def _build_commit_evidence(self, commits: list[Commit]) -> list[CommitEvidence]:
        """Convert Commit models to CommitEvidence structs."""

        def build_commit(c: Commit) -> CommitEvidence:
            return CommitEvidence(
                sha=c.sha,
                message=c.message,
                author_name=c.author_name,
                author_email=c.author_email,
                committed_at=c.committed_at,
                work_type=classify_commit(c, self._classification_config),
                is_merge_commit=is_merge_commit(c),
            )

        return self._build_classified_evidence(commits, build_commit)

    def _build_pr_evidence(self, prs: list[PullRequest]) -> list[PullRequestEvidence]:
        """Convert PullRequest models to PullRequestEvidence structs."""

        def build_pr(pr: PullRequest) -> PullRequestEvidence:
            return PullRequestEvidence(
                id=pr.id,
                number=pr.number,
                title=pr.title,
                author_login=pr.author_login,
                state=pr.state,
                labels=tuple(pr.labels),
                created_at=pr.created_at,
                merged_at=pr.merged_at,
                closed_at=pr.closed_at,
                work_type=classify_pull_request(pr, self._classification_config),
                is_draft=pr.is_draft,
            )

        return self._build_classified_evidence(prs, build_pr)

    def _build_issue_evidence(self, issues: list[Issue]) -> list[IssueEvidence]:
        """Convert Issue models to IssueEvidence structs."""

        def build_issue(i: Issue) -> IssueEvidence:
            return IssueEvidence(
                id=i.id,
                number=i.number,
                title=i.title,
                author_login=i.author_login,
                state=i.state,
                labels=tuple(i.labels),
                created_at=i.created_at,
                closed_at=i.closed_at,
                work_type=classify_issue(i, self._classification_config),
            )

        return self._build_classified_evidence(issues, build_issue)

    def _build_doc_evidence(
        self, doc_changes: list[DocumentationChange]
    ) -> list[DocumentationEvidence]:
        """Convert DocumentationChange models to DocumentationEvidence structs."""
        return [
            DocumentationEvidence(
                path=dc.path,
                change_type=dc.change_type,
                commit_sha=dc.commit_sha,
                occurred_at=dc.occurred_at,
                is_roadmap=dc.is_roadmap,
                is_adr=dc.is_adr,
            )
            for dc in doc_changes
        ]

    def _compute_work_type_groupings(
        self,
        commits: list[CommitEvidence],
        prs: list[PullRequestEvidence],
        issues: list[IssueEvidence],
    ) -> list[WorkTypeGrouping]:
        """Group events by work type for summary generation."""
        groupings = self._build_grouping_buckets(commits, prs, issues)
        return self._build_grouping_results(groupings)

    def _build_grouping_buckets(
        self,
        commits: list[CommitEvidence],
        prs: list[PullRequestEvidence],
        issues: list[IssueEvidence],
    ) -> dict[WorkType, dict[str, list[typ.Any]]]:
        """Bucket events by work type."""
        groupings: dict[WorkType, dict[str, list[typ.Any]]] = {
            work_type: {"commits": [], "prs": [], "issues": [], "titles": []}
            for work_type in WorkType
        }

        # Exclude merge commits from groupings
        for c in (c for c in commits if not c.is_merge_commit):
            groupings[c.work_type]["commits"].append(c)
            if c.message:
                groupings[c.work_type]["titles"].append(c.message[:100])

        for pr in prs:
            groupings[pr.work_type]["prs"].append(pr)
            groupings[pr.work_type]["titles"].append(pr.title)

        for issue in issues:
            groupings[issue.work_type]["issues"].append(issue)
            groupings[issue.work_type]["titles"].append(issue.title)

        return groupings

    def _build_grouping_results(
        self,
        groupings: dict[WorkType, dict[str, list[typ.Any]]],
    ) -> list[WorkTypeGrouping]:
        """Convert bucketed groupings to WorkTypeGrouping objects."""
        result = []
        for work_type, data in groupings.items():
            commit_count = len(data["commits"])
            pr_count = len(data["prs"])
            issue_count = len(data["issues"])

            # Skip empty groupings
            if not any((commit_count, pr_count, issue_count)):
                continue

            result.append(
                WorkTypeGrouping(
                    work_type=work_type,
                    commit_count=commit_count,
                    pr_count=pr_count,
                    issue_count=issue_count,
                    sample_titles=tuple(data["titles"][:5]),
                )
            )

        return result
