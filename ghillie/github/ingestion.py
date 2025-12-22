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

import msgspec
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ghillie.bronze import (
    GithubIngestionOffset,
    RawEventEnvelope,
    RawEventWriter,
)
from ghillie.catalogue.models import NoiseFilters
from ghillie.catalogue.storage import ComponentRecord, ProjectRecord, RepositoryRecord
from ghillie.common.time import utcnow

from .noise import CompiledNoiseFilters, compile_noise_filters

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


@dataclasses.dataclass(frozen=True, slots=True)
class _KindIngestionContext:
    """Context for ingesting a specific entity kind."""

    kind: typ.Literal["commit", "pull_request", "issue"]
    now: dt.datetime


@dataclasses.dataclass(frozen=True, slots=True)
class _RepositoryIngestionContext:
    """Context shared across ingestion for a single repository run."""

    repo: RepositoryInfo
    writer: RawEventWriter
    offsets: GithubIngestionOffset
    noise: CompiledNoiseFilters
    now: dt.datetime


_KIND_WATERMARK_ATTR: dict[typ.Literal["commit", "pull_request", "issue"], str] = {
    "commit": "last_commit_ingested_at",
    "pull_request": "last_pr_ingested_at",
    "issue": "last_issue_ingested_at",
}

_KIND_SEEN_ATTR: dict[typ.Literal["commit", "pull_request", "issue"], str] = {
    "commit": "last_commit_seen_at",
    "pull_request": "last_pr_seen_at",
    "issue": "last_issue_seen_at",
}

_KIND_CURSOR_ATTR: dict[typ.Literal["commit", "pull_request", "issue"], str] = {
    "commit": "last_commit_cursor",
    "pull_request": "last_pr_cursor",
    "issue": "last_issue_cursor",
}


class GitHubIngestionWorker:
    """Poll GitHub and write incremental activity into Bronze raw events."""

    def __init__(
        self,
        session_factory: SessionFactory,
        client: GitHubActivityClient,
        *,
        config: GitHubIngestionConfig | None = None,
        catalogue_session_factory: SessionFactory | None = None,
    ) -> None:
        """Create a worker bound to a database session factory and GitHub client."""
        self._session_factory = session_factory
        self._catalogue_sf = catalogue_session_factory or session_factory
        self._client = client
        self._config = config or GitHubIngestionConfig()

    async def ingest_repository(self, repo: RepositoryInfo) -> GitHubIngestionResult:
        """Ingest activity for a single repository."""
        if not repo.ingestion_enabled:
            return GitHubIngestionResult(repo_slug=repo.slug)

        run_started_at = utcnow()
        offsets = await self._load_or_create_offsets(repo.slug)
        writer = RawEventWriter(self._session_factory)
        noise = await self._compile_noise_filters(repo)
        context = _RepositoryIngestionContext(
            repo=repo,
            writer=writer,
            offsets=offsets,
            noise=noise,
            now=run_started_at,
        )

        commits = await self._ingest_kind(context, kind="commit")
        prs = await self._ingest_kind(context, kind="pull_request")
        issues = await self._ingest_kind(context, kind="issue")
        docs = await self._ingest_doc_changes(context)

        await self._persist_offsets(context.offsets)

        return GitHubIngestionResult(
            repo_slug=repo.slug,
            commits_ingested=commits,
            pull_requests_ingested=prs,
            issues_ingested=issues,
            doc_changes_ingested=docs,
        )

    async def _ingest_doc_changes(
        self,
        context: _RepositoryIngestionContext,
    ) -> int:
        offsets = context.offsets
        since = self._since_for(offsets.last_doc_ingested_at, now=context.now)
        after = offsets.last_doc_cursor
        resuming = after is not None
        result = await self._ingest_events_stream(
            context.repo,
            context.writer,
            self._client.iter_doc_changes(
                context.repo,
                since=since,
                documentation_paths=context.repo.documentation_paths,
                after=after,
            ),
            noise=context.noise,
        )
        self._update_doc_watermarks(offsets, result, resuming=resuming)
        return result.ingested

    def _update_doc_watermarks(
        self,
        offsets: GithubIngestionOffset,
        result: _StreamIngestionResult,
        *,
        resuming: bool,
    ) -> None:
        """Update doc change watermarks based on ingestion result."""
        offsets.last_doc_cursor = result.resume_cursor
        if result.truncated:
            offsets.last_doc_seen_at = _max_dt(
                offsets.last_doc_seen_at, result.max_seen
            )
            return

        offsets.last_doc_cursor = None
        if not resuming:
            if result.max_seen is not None:
                offsets.last_doc_ingested_at = result.max_seen
            return

        final_seen = offsets.last_doc_seen_at or result.max_seen
        if final_seen is not None:
            offsets.last_doc_ingested_at = final_seen
        offsets.last_doc_seen_at = None

    def _get_stream_for_kind(
        self,
        repo: RepositoryInfo,
        kind: typ.Literal["commit", "pull_request", "issue"],
        *,
        since: dt.datetime,
        after: str | None,
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Select the appropriate activity stream for the given kind."""
        if kind == "commit":
            return self._client.iter_commits(repo, since=since, after=after)
        if kind == "pull_request":
            return self._client.iter_pull_requests(repo, since=since, after=after)
        return self._client.iter_issues(repo, since=since, after=after)

    async def _ingest_kind(
        self,
        context: _RepositoryIngestionContext,
        *,
        kind: typ.Literal["commit", "pull_request", "issue"],
    ) -> int:
        watermark_attr = _KIND_WATERMARK_ATTR[kind]
        seen_attr = _KIND_SEEN_ATTR[kind]
        cursor_attr = _KIND_CURSOR_ATTR[kind]
        offsets = context.offsets
        current = typ.cast("dt.datetime | None", getattr(offsets, watermark_attr))
        since = self._since_for(current, now=context.now)
        after = typ.cast("str | None", getattr(offsets, cursor_attr))
        resuming = after is not None

        stream = self._get_stream_for_kind(context.repo, kind, since=since, after=after)

        result = await self._ingest_events_stream(
            context.repo, context.writer, stream, noise=context.noise
        )
        setattr(offsets, cursor_attr, result.resume_cursor)

        if result.truncated:
            setattr(
                offsets,
                seen_attr,
                _max_dt(getattr(offsets, seen_attr), result.max_seen),
            )
        elif resuming:
            setattr(offsets, cursor_attr, None)
            final_seen = typ.cast("dt.datetime | None", getattr(offsets, seen_attr))
            watermark = final_seen or result.max_seen
            if watermark is not None:
                setattr(offsets, watermark_attr, watermark)
            setattr(offsets, seen_attr, None)
        else:
            setattr(offsets, cursor_attr, None)
            if result.max_seen is not None:
                setattr(offsets, watermark_attr, result.max_seen)
        return result.ingested

    async def _ingest_events_stream(
        self,
        repo: RepositoryInfo,
        writer: RawEventWriter,
        events: typ.AsyncIterator[GitHubIngestedEvent],
        *,
        noise: CompiledNoiseFilters,
    ) -> _StreamIngestionResult:
        max_seen: dt.datetime | None = None
        last_cursor: str | None = None
        ingested = 0
        limit = self._config.max_events_per_kind
        seen = 0
        truncated = False

        async for event in events:
            if seen >= limit:
                truncated = True
                break
            seen += 1
            envelope = RawEventEnvelope(
                source_system="github",
                source_event_id=event.source_event_id,
                event_type=event.event_type,
                repo_external_id=repo.slug,
                occurred_at=event.occurred_at,
                payload=event.payload,
            )
            last_cursor = event.cursor
            if not noise.should_drop(event):
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

    async def _compile_noise_filters(
        self, repo: RepositoryInfo
    ) -> CompiledNoiseFilters:
        """Load project noise configuration for the repository and compile it."""
        try:
            async with self._catalogue_sf() as session:
                query = (
                    select(ProjectRecord.noise)
                    .join(
                        ComponentRecord, ComponentRecord.project_id == ProjectRecord.id
                    )
                    .join(
                        RepositoryRecord,
                        ComponentRecord.repository_id == RepositoryRecord.id,
                    )
                    .where(
                        RepositoryRecord.owner == repo.owner,
                        RepositoryRecord.name == repo.name,
                    )
                )
                if repo.estate_id is not None:
                    query = query.where(ProjectRecord.estate_id == repo.estate_id)
                rows = (await session.scalars(query)).all()
        except SQLAlchemyError:
            rows = []

        filters = [
            msgspec.convert(row, NoiseFilters) for row in rows if isinstance(row, dict)
        ]
        return compile_noise_filters(filters)


def _max_dt(left: dt.datetime | None, right: dt.datetime | None) -> dt.datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)
