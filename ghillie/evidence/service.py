"""Evidence bundle generation service."""

from __future__ import annotations

import dataclasses as dc
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
    classify_entity,
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
    from sqlalchemy.sql.elements import SQLColumnExpression

    # Alias for SQLColumnExpression accepting datetime or nullable datetime
    DateTimeColumnExpr = (
        SQLColumnExpression[dt.datetime] | SQLColumnExpression[dt.datetime | None]
    )

T = typ.TypeVar("T")


@dc.dataclass(slots=True, frozen=True)
class _QueryContext:
    """Context for querying repository events within a time window."""

    repository_id: str
    window_start: dt.datetime
    window_end: dt.datetime


@dc.dataclass(slots=True)
class _WorkTypeBucket:
    """Bucket for grouping events by work type."""

    commits: list[CommitEvidence]
    prs: list[PullRequestEvidence]
    issues: list[IssueEvidence]
    titles: list[str]


class _ClassifiableEvidence(typ.Protocol):
    """Protocol for evidence with work type and title."""

    work_type: WorkType
    title: str


# TypeVar for entities that satisfy the ClassifiableEvidence protocol
_E = typ.TypeVar("_E", bound=_ClassifiableEvidence)


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

    async def _fetch_repo_entities_in_window(
        self,
        session: AsyncSession,
        model: type[T],
        ctx: _QueryContext,
        time_field: DateTimeColumnExpr,
    ) -> list[T]:
        """Fetch entities within a time window.

        Parameters
        ----------
        session
            Database session.
        model
            SQLAlchemy model class to query.
        ctx
            Query context with repository ID and time window.
        time_field
            Column to use for time filtering.

        Returns
        -------
        list[T]
            List of matching entities.

        """
        stmt = (
            select(model)
            .where(
                model.repo_id == ctx.repository_id,  # type: ignore[attr-defined]
                time_field >= ctx.window_start,
                time_field < ctx.window_end,
            )
            .order_by(time_field.desc())
        )
        return list((await session.scalars(stmt)).all())

    async def _fetch_all_events(
        self,
        session: AsyncSession,
        ctx: _QueryContext,
    ) -> tuple[list[Commit], list[PullRequest], list[Issue], list[DocumentationChange]]:
        """Fetch all events within the window.

        Returns
        -------
        tuple[list[Commit], list[PullRequest], list[Issue], list[DocumentationChange]]
            A tuple of (commits, prs, issues, doc_changes).

        """
        commits = await self._fetch_repo_entities_in_window(
            session,
            Commit,
            ctx,
            Commit.committed_at,
        )
        prs = await self._fetch_pull_requests(session, ctx)
        issues = await self._fetch_issues(session, ctx)
        doc_changes = await self._fetch_repo_entities_in_window(
            session,
            DocumentationChange,
            ctx,
            DocumentationChange.occurred_at,
        )
        return commits, prs, issues, doc_changes

    def _build_all_evidence(
        self,
        commits: list[Commit],
        prs: list[PullRequest],
        issues: list[Issue],
        doc_changes: list[DocumentationChange],
    ) -> tuple[
        list[CommitEvidence],
        list[PullRequestEvidence],
        list[IssueEvidence],
        list[DocumentationEvidence],
    ]:
        """Build classified evidence from all event types.

        Returns
        -------
        tuple
            A tuple of (commit_evidence, pr_evidence, issue_evidence, doc_evidence).

        """
        commit_evidence = self._build_commit_evidence(commits)
        pr_evidence = self._build_pr_evidence(prs)
        issue_evidence = self._build_issue_evidence(issues)
        doc_evidence = self._build_doc_evidence(doc_changes)
        return commit_evidence, pr_evidence, issue_evidence, doc_evidence

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
        ctx = _QueryContext(
            repository_id=repository_id,
            window_start=window_start,
            window_end=window_end,
        )
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

            # Fetch all events within window
            commits, prs, issues, doc_changes = await self._fetch_all_events(
                session, ctx
            )

            # Collect event fact IDs for coverage tracking
            event_fact_ids = await self._fetch_event_fact_ids(session, repo.slug, ctx)

            # Build evidence with classification
            commit_evidence, pr_evidence, issue_evidence, doc_evidence = (
                self._build_all_evidence(commits, prs, issues, doc_changes)
            )

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
        match status:
            case None:
                return ReportStatus.UNKNOWN
            case str() as s:
                try:
                    return ReportStatus(s.lower())
                except ValueError:
                    return ReportStatus.UNKNOWN
            case _:
                try:
                    return ReportStatus(str(status).lower())
                except ValueError:
                    return ReportStatus.UNKNOWN

    async def _fetch_pull_requests(
        self,
        session: AsyncSession,
        ctx: _QueryContext,
    ) -> list[PullRequest]:
        """Fetch PRs created, merged, or closed within the window."""
        stmt = (
            select(PullRequest)
            .where(
                PullRequest.repo_id == ctx.repository_id,
                # Include PRs created, merged, or closed in window
                or_(
                    (PullRequest.created_at >= ctx.window_start)
                    & (PullRequest.created_at < ctx.window_end),
                    (PullRequest.merged_at >= ctx.window_start)
                    & (PullRequest.merged_at < ctx.window_end),
                    (PullRequest.closed_at >= ctx.window_start)
                    & (PullRequest.closed_at < ctx.window_end),
                ),
            )
            .order_by(PullRequest.created_at.desc())
        )
        return list((await session.scalars(stmt)).all())

    async def _fetch_issues(
        self,
        session: AsyncSession,
        ctx: _QueryContext,
    ) -> list[Issue]:
        """Fetch issues created or closed within the window."""
        stmt = (
            select(Issue)
            .where(
                Issue.repo_id == ctx.repository_id,
                or_(
                    (Issue.created_at >= ctx.window_start)
                    & (Issue.created_at < ctx.window_end),
                    (Issue.closed_at >= ctx.window_start)
                    & (Issue.closed_at < ctx.window_end),
                ),
            )
            .order_by(Issue.created_at.desc())
        )
        return list((await session.scalars(stmt)).all())

    async def _fetch_event_fact_ids(
        self,
        session: AsyncSession,
        repo_external_id: str,
        ctx: _QueryContext,
    ) -> list[int]:
        """Fetch EventFact IDs for coverage tracking."""
        stmt = select(EventFact.id).where(
            EventFact.repo_external_id == repo_external_id,
            EventFact.occurred_at >= ctx.window_start,
            EventFact.occurred_at < ctx.window_end,
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

        return [build_commit(c) for c in commits]

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
                work_type=classify_entity(pr, self._classification_config),
                is_draft=pr.is_draft,
            )

        return [build_pr(pr) for pr in prs]

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
                work_type=classify_entity(i, self._classification_config),
            )

        return [build_issue(i) for i in issues]

    def _build_doc_evidence(
        self, doc_changes: list[DocumentationChange]
    ) -> list[DocumentationEvidence]:
        """Convert DocumentationChange models to DocumentationEvidence structs."""
        return [
            DocumentationEvidence(
                path=doc.path,
                change_type=doc.change_type,
                commit_sha=doc.commit_sha,
                occurred_at=doc.occurred_at,
                is_roadmap=doc.is_roadmap,
                is_adr=doc.is_adr,
            )
            for doc in doc_changes
        ]

    def _populate_entity_bucket(
        self,
        buckets: dict[WorkType, _WorkTypeBucket],
        entities: list[_E],
        get_bucket_list: typ.Callable[[_WorkTypeBucket], list[_E]],
    ) -> None:
        """Populate buckets with entities (PRs or issues).

        Parameters
        ----------
        buckets
            Dictionary mapping work types to their buckets.
        entities
            List of evidence entities to process.
        get_bucket_list
            Function that extracts the appropriate list from a bucket.

        """
        for entity in entities:
            bucket = buckets[entity.work_type]
            get_bucket_list(bucket).append(entity)
            bucket.titles.append(entity.title)

    def _populate_commit_bucket(
        self,
        buckets: dict[WorkType, _WorkTypeBucket],
        commits: list[CommitEvidence],
    ) -> None:
        """Populate buckets with non-merge commits.

        Excludes merge commits from work-type groupings to avoid double-counting.
        Appends the first 100 characters of the commit message as a sample title.

        Parameters
        ----------
        buckets
            Dictionary mapping work types to their buckets.
        commits
            List of commit evidence to process.

        """
        for commit in commits:
            if commit.is_merge_commit:
                continue
            bucket = buckets[commit.work_type]
            bucket.commits.append(commit)
            if commit.message:
                bucket.titles.append(commit.message[:100])

    def _populate_pr_bucket(
        self,
        buckets: dict[WorkType, _WorkTypeBucket],
        prs: list[PullRequestEvidence],
    ) -> None:
        """Populate buckets with pull requests."""
        self._populate_entity_bucket(buckets, prs, lambda b: b.prs)

    def _populate_issue_bucket(
        self,
        buckets: dict[WorkType, _WorkTypeBucket],
        issues: list[IssueEvidence],
    ) -> None:
        """Populate buckets with issues."""
        self._populate_entity_bucket(buckets, issues, lambda b: b.issues)

    def _build_grouping_from_bucket(
        self,
        work_type: WorkType,
        bucket: _WorkTypeBucket,
    ) -> WorkTypeGrouping | None:
        """Build a WorkTypeGrouping from a bucket, or None if empty.

        Parameters
        ----------
        work_type
            The work type for this grouping.
        bucket
            The bucket containing events for this work type.

        Returns
        -------
        WorkTypeGrouping | None
            The grouping if any events exist, otherwise None.

        """
        commit_count = len(bucket.commits)
        pr_count = len(bucket.prs)
        issue_count = len(bucket.issues)

        if not any((commit_count, pr_count, issue_count)):
            return None

        return WorkTypeGrouping(
            work_type=work_type,
            commit_count=commit_count,
            pr_count=pr_count,
            issue_count=issue_count,
            sample_titles=tuple(bucket.titles[:5]),
        )

    def _compute_work_type_groupings(
        self,
        commits: list[CommitEvidence],
        prs: list[PullRequestEvidence],
        issues: list[IssueEvidence],
    ) -> list[WorkTypeGrouping]:
        """Group events by work type for summary generation."""
        buckets: dict[WorkType, _WorkTypeBucket] = {
            wt: _WorkTypeBucket([], [], [], []) for wt in WorkType
        }

        self._populate_commit_bucket(buckets, commits)
        self._populate_pr_bucket(buckets, prs)
        self._populate_issue_bucket(buckets, issues)

        results: list[WorkTypeGrouping] = []
        for work_type, bucket in buckets.items():
            grouping = self._build_grouping_from_bucket(work_type, bucket)
            if grouping is not None:
                results.append(grouping)

        return results
