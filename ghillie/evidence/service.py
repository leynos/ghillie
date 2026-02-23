"""Evidence bundle generation service.

This module provides the EvidenceBundleService class for constructing evidence
bundles that aggregate repository activity within a reporting window. Evidence
bundles are used by the LLM layer to generate human-readable status reports.

The service queries the Silver layer (normalized GitHub events) and transforms
them into classified evidence items organized by work type, ready for
summarization.

Example:
-------
Create an engine and session factory, then build a bundle for a repository:

>>> from datetime import datetime, timezone
>>> from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
>>> from ghillie.bronze import init_bronze_storage
>>> from ghillie.silver import init_silver_storage
>>> from ghillie.evidence.service import EvidenceBundleService
>>>
>>> # Set up database connection
>>> engine = create_async_engine("sqlite+aiosqlite:///ghillie.db")
>>> await init_bronze_storage(engine)
>>> await init_silver_storage(engine)
>>> session_factory = async_sessionmaker(engine, expire_on_commit=False)
>>>
>>> # Build the evidence bundle
>>> service = EvidenceBundleService(session_factory)
>>> bundle = await service.build_bundle(
...     repository_id="550e8400-e29b-41d4-a716-446655440000",
...     window_start=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
...     window_end=datetime(2025, 1, 8, 0, 0, 0, tzinfo=timezone.utc),
... )
>>>
>>> # Access bundle properties
>>> print(bundle.repository.slug)  # "owner/repo-name"
>>> print(bundle.total_event_count)  # Total commits, PRs, issues, doc changes
>>> print(len(bundle.commits))  # Number of commits in window
>>> print(len(bundle.work_type_groupings))  # Work types with activity

"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from sqlalchemy import select, tuple_
from sqlalchemy.orm import selectinload

from ghillie.common.time import utcnow
from ghillie.gold.storage import Report, ReportCoverage, ReportScope
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
from .event_targets import EventTargetExtractor, EventTargets
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
    import collections.abc as cabc
    import datetime as dt

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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


@dc.dataclass(frozen=True, slots=True)
class _WindowQuery:
    """Encapsulates a repository and time window for querying events.

    Parameters
    ----------
    repository_id
        The repository identifier.
    window_start
        Start of the window (inclusive).
    window_end
        End of the window (exclusive).

    """

    repository_id: str
    window_start: dt.datetime
    window_end: dt.datetime


_DOC_CHANGE_KEY_CHUNK_SIZE = 500


class EvidenceBundleService:
    """Generates evidence bundles for repository status reporting.

    This service queries the Silver layer to construct evidence bundles
    that aggregate all activity within a reporting window, ready for
    LLM summarization.

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

    _extractor = EventTargetExtractor()

    async def _fetch_uncovered_event_facts(
        self,
        session: AsyncSession,
        repo_external_id: str,
        repository_id: str,
        window: _WindowQuery,
    ) -> list[EventFact]:
        """Fetch EventFacts in the window, excluding repository-scope coverage."""
        coverage_exists = (
            select(ReportCoverage.id)
            .join(Report, ReportCoverage.report_id == Report.id)
            .where(
                ReportCoverage.event_fact_id == EventFact.id,
                Report.scope == ReportScope.REPOSITORY,
                Report.repository_id == repository_id,
            )
            .exists()
        )

        stmt = (
            select(EventFact)
            .where(
                EventFact.repo_external_id == repo_external_id,
                EventFact.occurred_at >= window.window_start,
                EventFact.occurred_at < window.window_end,
                ~coverage_exists,
            )
            .order_by(EventFact.occurred_at.desc(), EventFact.id.desc())
        )
        return list((await session.scalars(stmt)).all())

    # Type-safe fetch wrappers: These methods appear similar but provide
    # distinct type signatures for different entity types, keeping call sites
    # clear and type checking reliable.
    async def _fetch_commits_by_sha(
        self,
        session: AsyncSession,
        repository_id: str,
        shas: set[str],
    ) -> list[Commit]:
        """Fetch commits by SHA for a repository."""
        if not shas:
            return []
        stmt = (
            select(Commit)
            .where(
                Commit.repo_id == repository_id,
                Commit.sha.in_(shas),
            )
            .order_by(Commit.committed_at.desc())
        )
        return list((await session.scalars(stmt)).all())

    async def _fetch_pull_requests_by_id(
        self,
        session: AsyncSession,
        repository_id: str,
        ids: set[int],
    ) -> list[PullRequest]:
        """Fetch pull requests by id for a repository."""
        if not ids:
            return []
        stmt = (
            select(PullRequest)
            .where(
                PullRequest.repo_id == repository_id,
                PullRequest.id.in_(ids),
            )
            .order_by(PullRequest.created_at.desc())
        )
        return list((await session.scalars(stmt)).all())

    async def _fetch_issues_by_id(
        self,
        session: AsyncSession,
        repository_id: str,
        ids: set[int],
    ) -> list[Issue]:
        """Fetch issues by id for a repository."""
        if not ids:
            return []
        stmt = (
            select(Issue)
            .where(
                Issue.repo_id == repository_id,
                Issue.id.in_(ids),
            )
            .order_by(Issue.created_at.desc())
        )
        return list((await session.scalars(stmt)).all())

    async def _fetch_doc_changes_by_key(
        self,
        session: AsyncSession,
        repository_id: str,
        keys: set[tuple[str, str]],
    ) -> list[DocumentationChange]:
        """Fetch documentation changes by commit/path keys.

        Chunk large key sets to avoid parameter explosion in tuple IN clauses.

        """
        if not keys:
            return []
        key_list = list(keys)
        if len(key_list) <= _DOC_CHANGE_KEY_CHUNK_SIZE:
            stmt = (
                select(DocumentationChange)
                .where(
                    DocumentationChange.repo_id == repository_id,
                    tuple_(
                        DocumentationChange.commit_sha, DocumentationChange.path
                    ).in_(key_list),
                )
                .order_by(DocumentationChange.occurred_at.desc())
            )
            return list((await session.scalars(stmt)).all())

        docs: list[DocumentationChange] = []
        for offset in range(0, len(key_list), _DOC_CHANGE_KEY_CHUNK_SIZE):
            chunk = key_list[offset : offset + _DOC_CHANGE_KEY_CHUNK_SIZE]
            stmt = (
                select(DocumentationChange)
                .where(
                    DocumentationChange.repo_id == repository_id,
                    tuple_(
                        DocumentationChange.commit_sha, DocumentationChange.path
                    ).in_(chunk),
                )
                .order_by(DocumentationChange.occurred_at.desc())
            )
            docs.extend((await session.scalars(stmt)).all())
        return sorted(docs, key=lambda doc: doc.occurred_at, reverse=True)

    async def _fetch_repository_context(
        self,
        session: AsyncSession,
        repository_id: str,
        window_start: dt.datetime,
    ) -> tuple[Repository, list[PreviousReportSummary]]:
        """Fetch repository metadata and previous reports for a bundle."""
        repo = await self._fetch_repository(session, repository_id)
        if repo is None:
            raise ValueError(f"Repository not found: {repository_id}")  # noqa: TRY003
        previous_reports = await self._fetch_previous_reports(
            session, repository_id, window_start
        )
        return repo, previous_reports

    async def _fetch_bundle_entities(
        self,
        session: AsyncSession,
        repository_id: str,
        repo_slug: str,
        window: _WindowQuery,
    ) -> tuple[
        list[Commit],
        list[PullRequest],
        list[Issue],
        list[DocumentationChange],
        list[int],
    ]:
        """Fetch entity lists and event fact identifiers for a bundle."""
        event_facts = await self._fetch_uncovered_event_facts(
            session, repo_slug, repository_id, window
        )
        targets: EventTargets = self._extractor.extract(event_facts)
        commits = await self._fetch_commits_by_sha(
            session, repository_id, targets.commit_shas
        )
        prs = await self._fetch_pull_requests_by_id(
            session, repository_id, targets.pull_request_ids
        )
        issues = await self._fetch_issues_by_id(
            session, repository_id, targets.issue_ids
        )
        doc_changes = await self._fetch_doc_changes_by_key(
            session, repository_id, targets.doc_change_keys
        )
        event_fact_ids = [fact.id for fact in event_facts]
        return commits, prs, issues, doc_changes, event_fact_ids

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
        """Build classified evidence from all event types."""
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

        Coverage exclusion is repository-scope only: events already covered by
        repository reports are excluded, while project or estate coverage does
        not affect repository bundles.

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
        window = _WindowQuery(
            repository_id=repository_id,
            window_start=window_start,
            window_end=window_end,
        )
        async with self._session_factory() as session:
            repo, previous_reports = await self._fetch_repository_context(
                session, repository_id, window_start
            )
            entities = await self._fetch_bundle_entities(
                session, repository_id, repo.slug, window
            )
            commits, prs, issues, doc_changes, event_fact_ids = entities
            commit_evidence, pr_evidence, issue_evidence, doc_evidence = (
                self._build_all_evidence(commits, prs, issues, doc_changes)
            )
            groupings = self._compute_work_type_groupings(
                commit_evidence, pr_evidence, issue_evidence
            )
            return RepositoryEvidenceBundle(
                repository=self._build_repository_metadata(repo),
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

    # Evidence builders: These methods follow a consistent transformation
    # pattern (ORM → Evidence struct) but handle entity-specific fields and
    # classification logic. The structural similarity is inherent to the
    # domain model and aids consistency across evidence types.
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

    def _populate_entity_bucket[E: _ClassifiableEvidence](
        self,
        buckets: dict[WorkType, _WorkTypeBucket],
        entities: cabc.Sequence[E],
        get_bucket_list: cabc.Callable[[_WorkTypeBucket], list[E]],
    ) -> None:
        """Populate buckets with entities (PRs or issues)."""
        for entity in entities:
            bucket = buckets[entity.work_type]
            get_bucket_list(bucket).append(entity)
            bucket.titles.append(entity.title)

    def _populate_commit_bucket(
        self,
        buckets: dict[WorkType, _WorkTypeBucket],
        commits: list[CommitEvidence],
    ) -> None:
        """Populate buckets with non-merge commits."""
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
        """Build a WorkTypeGrouping from a bucket, or None if empty."""
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
