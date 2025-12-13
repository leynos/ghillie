"""Incremental GitHub ingestion worker.

The worker polls GitHub for commits, pull requests, issues, and documentation
changes per managed repository and appends them to the Bronze `raw_events`
store. It records a per-repository watermark so subsequent runs ingest only
newer activity, with an overlap window to tolerate clock skew and eventual
consistency.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import typing as typ

from sqlalchemy import select

from ghillie.bronze import GithubIngestionOffset, RawEventEnvelope, RawEventWriter
from ghillie.common.time import utcnow

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.registry.models import RepositoryInfo

    from .client import GitHubActivityClient
    from .models import GitHubIngestedEvent

    type SessionFactory = async_sessionmaker[AsyncSession]


@dataclasses.dataclass(frozen=True, slots=True)
class GitHubIngestionConfig:
    """Runtime knobs for incremental ingestion."""

    initial_lookback: dt.timedelta = dt.timedelta(days=7)
    overlap: dt.timedelta = dt.timedelta(minutes=5)
    max_events_per_kind: int = 500


@dataclasses.dataclass(frozen=True, slots=True)
class GitHubIngestionResult:
    """Summary of a single repository ingestion run."""

    repo_slug: str
    commits_ingested: int = 0
    pull_requests_ingested: int = 0
    issues_ingested: int = 0
    doc_changes_ingested: int = 0


class GitHubIngestionWorker:
    """Poll GitHub and write incremental activity into Bronze raw events."""

    def __init__(
        self,
        session_factory: SessionFactory,
        client: GitHubActivityClient,
        *,
        config: GitHubIngestionConfig | None = None,
    ) -> None:
        """Create a worker bound to a database session factory and GitHub client."""
        self._session_factory = session_factory
        self._client = client
        self._config = config or GitHubIngestionConfig()

    async def ingest_repository(self, repo: RepositoryInfo) -> GitHubIngestionResult:
        """Ingest activity for a single repository."""
        if not repo.ingestion_enabled:
            return GitHubIngestionResult(repo_slug=repo.slug)

        offsets = await self._load_or_create_offsets(repo.slug)
        writer = RawEventWriter(self._session_factory)

        commits = await self._ingest_kind(
            repo,
            writer,
            offsets,
            kind="commit",
        )
        prs = await self._ingest_kind(
            repo,
            writer,
            offsets,
            kind="pull_request",
        )
        issues = await self._ingest_kind(
            repo,
            writer,
            offsets,
            kind="issue",
        )
        docs = await self._ingest_doc_changes(repo, writer, offsets)

        await self._persist_offsets(offsets)

        return GitHubIngestionResult(
            repo_slug=repo.slug,
            commits_ingested=commits,
            pull_requests_ingested=prs,
            issues_ingested=issues,
            doc_changes_ingested=docs,
        )

    async def _ingest_doc_changes(
        self,
        repo: RepositoryInfo,
        writer: RawEventWriter,
        offsets: GithubIngestionOffset,
    ) -> int:
        since = self._since_for(offsets.last_doc_ingested_at)
        ingested, watermark = await self._ingest_events_stream(
            repo,
            writer,
            self._client.iter_doc_changes(
                repo, since=since, documentation_paths=repo.documentation_paths
            ),
        )
        if watermark is not None:
            offsets.last_doc_ingested_at = watermark
        return ingested

    async def _ingest_kind(
        self,
        repo: RepositoryInfo,
        writer: RawEventWriter,
        offsets: GithubIngestionOffset,
        *,
        kind: typ.Literal["commit", "pull_request", "issue"],
    ) -> int:
        watermark_attr = {
            "commit": "last_commit_ingested_at",
            "pull_request": "last_pr_ingested_at",
            "issue": "last_issue_ingested_at",
        }[kind]
        current = typ.cast("dt.datetime | None", getattr(offsets, watermark_attr))
        since = self._since_for(current)

        if kind == "commit":
            stream = self._client.iter_commits(repo, since=since)
        elif kind == "pull_request":
            stream = self._client.iter_pull_requests(repo, since=since)
        else:
            stream = self._client.iter_issues(repo, since=since)

        ingested, watermark = await self._ingest_events_stream(repo, writer, stream)
        if watermark is not None:
            setattr(offsets, watermark_attr, watermark)
        return ingested

    async def _ingest_events_stream(
        self,
        repo: RepositoryInfo,
        writer: RawEventWriter,
        events: typ.AsyncIterator[GitHubIngestedEvent],
    ) -> tuple[int, dt.datetime | None]:
        max_seen: dt.datetime | None = None
        ingested = 0
        limit = self._config.max_events_per_kind

        async for event in events:
            if ingested >= limit:
                break
            envelope = RawEventEnvelope(
                source_system="github",
                source_event_id=event.source_event_id,
                event_type=event.event_type,
                repo_external_id=repo.slug,
                occurred_at=event.occurred_at,
                payload=event.payload,
            )
            await writer.ingest(envelope)
            ingested += 1
            if max_seen is None or event.occurred_at > max_seen:
                max_seen = event.occurred_at

        return ingested, max_seen

    def _since_for(self, watermark: dt.datetime | None) -> dt.datetime:
        now = utcnow()
        baseline = watermark or (now - self._config.initial_lookback)
        return baseline - self._config.overlap

    async def _load_or_create_offsets(self, repo_slug: str) -> GithubIngestionOffset:
        async with self._session_factory() as session, session.begin():
            existing = await session.scalar(
                select(GithubIngestionOffset).where(
                    GithubIngestionOffset.repo_external_id == repo_slug
                )
            )
            if existing is not None:
                return existing

            offsets = GithubIngestionOffset(repo_external_id=repo_slug)
            session.add(offsets)
            await session.flush()
            return offsets

    async def _persist_offsets(self, offsets: GithubIngestionOffset) -> None:
        async with self._session_factory() as session, session.begin():
            await session.merge(offsets)
