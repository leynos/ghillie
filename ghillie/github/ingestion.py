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

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ghillie.bronze import (
    GithubIngestionOffset,
    RawEvent,
    RawEventEnvelope,
    RawEventWriter,
)
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


@dataclasses.dataclass(frozen=True, slots=True)
class _StreamIngestionResult:
    """Outcome of ingesting a single activity stream."""

    ingested: int
    max_seen: dt.datetime | None
    resume_cursor: str | None
    truncated: bool


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

        run_started_at = utcnow()
        offsets = await self._load_or_create_offsets(repo.slug)
        writer = RawEventWriter(self._session_factory)

        commits = await self._ingest_kind(
            repo,
            writer,
            offsets,
            kind="commit",
            now=run_started_at,
        )
        prs = await self._ingest_kind(
            repo,
            writer,
            offsets,
            kind="pull_request",
            now=run_started_at,
        )
        issues = await self._ingest_kind(
            repo,
            writer,
            offsets,
            kind="issue",
            now=run_started_at,
        )
        docs = await self._ingest_doc_changes(repo, writer, offsets, now=run_started_at)

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
        *,
        now: dt.datetime,
    ) -> int:
        since = self._since_for(offsets.last_doc_ingested_at, now=now)
        result = await self._ingest_events_stream(
            repo,
            writer,
            self._client.iter_doc_changes(
                repo, since=since, documentation_paths=repo.documentation_paths
            ),
        )
        if result.max_seen is not None and not result.truncated:
            offsets.last_doc_ingested_at = result.max_seen
        return result.ingested

    async def _ingest_kind(  # noqa: PLR0913
        self,
        repo: RepositoryInfo,
        writer: RawEventWriter,
        offsets: GithubIngestionOffset,
        *,
        kind: typ.Literal["commit", "pull_request", "issue"],
        now: dt.datetime,
    ) -> int:
        watermark_attr = {
            "commit": "last_commit_ingested_at",
            "pull_request": "last_pr_ingested_at",
            "issue": "last_issue_ingested_at",
        }[kind]
        cursor_attr = {
            "commit": "last_commit_cursor",
            "pull_request": "last_pr_cursor",
            "issue": "last_issue_cursor",
        }[kind]
        current = typ.cast("dt.datetime | None", getattr(offsets, watermark_attr))
        since = self._since_for(current, now=now)
        after = typ.cast("str | None", getattr(offsets, cursor_attr))

        if kind == "commit":
            stream = self._client.iter_commits(repo, since=since, after=after)
        elif kind == "pull_request":
            stream = self._client.iter_pull_requests(repo, since=since, after=after)
        else:
            stream = self._client.iter_issues(repo, since=since, after=after)

        result = await self._ingest_events_stream(repo, writer, stream)
        setattr(offsets, cursor_attr, result.resume_cursor)
        if result.resume_cursor is None and result.max_seen is not None:
            if after is None:
                setattr(offsets, watermark_attr, result.max_seen)
            else:
                latest = await self._latest_ingested_at(repo.slug, kind=kind)
                if latest is not None:
                    setattr(offsets, watermark_attr, latest)
        return result.ingested

    async def _ingest_events_stream(
        self,
        repo: RepositoryInfo,
        writer: RawEventWriter,
        events: typ.AsyncIterator[GitHubIngestedEvent],
    ) -> _StreamIngestionResult:
        max_seen: dt.datetime | None = None
        last_cursor: str | None = None
        ingested = 0
        limit = self._config.max_events_per_kind
        truncated = False

        async for event in events:
            if ingested >= limit:
                truncated = True
                break
            last_cursor = event.cursor
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

        resume_cursor = last_cursor if truncated else None
        return _StreamIngestionResult(
            ingested=ingested,
            max_seen=max_seen,
            resume_cursor=resume_cursor,
            truncated=truncated,
        )

    def _since_for(
        self, watermark: dt.datetime | None, *, now: dt.datetime
    ) -> dt.datetime:
        """Compute the lower bound timestamp for a kind ingestion run."""
        baseline = watermark or (now - self._config.initial_lookback)
        return baseline - self._config.overlap

    async def _load_or_create_offsets(self, repo_slug: str) -> GithubIngestionOffset:
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(GithubIngestionOffset).where(
                    GithubIngestionOffset.repo_external_id == repo_slug
                )
            )
            if existing is not None:
                return existing

            offsets = GithubIngestionOffset(repo_external_id=repo_slug)
            session.add(offsets)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(GithubIngestionOffset).where(
                        GithubIngestionOffset.repo_external_id == repo_slug
                    )
                )
                if existing is not None:
                    return existing
                raise
            await session.refresh(offsets)
            return offsets

    async def _persist_offsets(self, offsets: GithubIngestionOffset) -> None:
        async with self._session_factory() as session, session.begin():
            await session.merge(offsets)

    async def _latest_ingested_at(
        self, repo_slug: str, *, kind: typ.Literal["commit", "pull_request", "issue"]
    ) -> dt.datetime | None:
        """Return the latest occurred_at persisted for a given repo and kind."""
        event_type = {
            "commit": "github.commit",
            "pull_request": "github.pull_request",
            "issue": "github.issue",
        }[kind]
        async with self._session_factory() as session:
            return await session.scalar(
                select(func.max(RawEvent.occurred_at)).where(
                    RawEvent.repo_external_id == repo_slug,
                    RawEvent.event_type == event_type,
                )
            )
