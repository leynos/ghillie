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
import logging
import typing as typ

import msgspec
from sqlalchemy import select
from sqlalchemy.exc import (
    IntegrityError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)

from ghillie.bronze import (
    GithubIngestionOffset,
    RawEventEnvelope,
    RawEventWriter,
)
from ghillie.catalogue.models import NoiseFilters
from ghillie.catalogue.storage import ComponentRecord, ProjectRecord, RepositoryRecord
from ghillie.common.time import utcnow

from .noise import CompiledNoiseFilters, compile_noise_filters
from .observability import (
    IngestionEventLogger,
    IngestionRunContext,
    StreamTruncationDetails,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.registry.models import RepositoryInfo

    from .client import GitHubActivityClient
    from .models import GitHubIngestedEvent

    type SessionFactory = async_sessionmaker[AsyncSession]

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class GitHubIngestionConfig:
    """Runtime knobs for incremental ingestion."""

    initial_lookback: dt.timedelta = dt.timedelta(days=7)
    overlap: dt.timedelta = dt.timedelta(minutes=5)
    max_events_per_kind: int = 500
    catalogue_session_factory: SessionFactory | None = None


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


@dataclasses.dataclass(frozen=True, slots=True)
class _WatermarkAttrs:
    cursor: str
    seen: str
    watermark: str


_DOC_WATERMARK_ATTRS = _WatermarkAttrs(
    cursor="last_doc_cursor",
    seen="last_doc_seen_at",
    watermark="last_doc_ingested_at",
)


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
        event_logger: IngestionEventLogger | None = None,
    ) -> None:
        """Create a worker bound to a database session factory and GitHub client."""
        self._session_factory = session_factory
        self._client = client
        resolved_config = config or GitHubIngestionConfig()
        self._config = resolved_config
        self._catalogue_sf = (
            resolved_config.catalogue_session_factory or session_factory
        )
        self._event_logger = event_logger or IngestionEventLogger()

    async def ingest_repository(self, repo: RepositoryInfo) -> GitHubIngestionResult:
        """Ingest activity for a single repository."""
        if not repo.ingestion_enabled:
            return GitHubIngestionResult(repo_slug=repo.slug)

        run_started_at = utcnow()
        obs_context = IngestionRunContext(
            repo_slug=repo.slug,
            estate_id=repo.estate_id,
            started_at=run_started_at,
        )
        self._event_logger.log_run_started(obs_context)

        try:
            result = await self._ingest_repository_inner(repo, run_started_at)
        except BaseException as exc:
            duration = utcnow() - run_started_at
            self._event_logger.log_run_failed(obs_context, exc, duration)
            raise

        duration = utcnow() - run_started_at
        self._event_logger.log_run_completed(obs_context, result, duration)
        return result

    async def _ingest_repository_inner(
        self, repo: RepositoryInfo, run_started_at: dt.datetime
    ) -> GitHubIngestionResult:
        """Inner ingestion logic separated for observability wrapping."""
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
        obs_context = IngestionRunContext(
            repo_slug=repo.slug,
            estate_id=repo.estate_id,
            started_at=run_started_at,
        )

        commits = await self._ingest_kind_with_logging(context, obs_context, "commit")
        prs = await self._ingest_kind_with_logging(context, obs_context, "pull_request")
        issues = await self._ingest_kind_with_logging(context, obs_context, "issue")
        docs = await self._ingest_doc_changes_with_logging(context, obs_context)

        await self._persist_offsets(context.offsets)

        return GitHubIngestionResult(
            repo_slug=repo.slug,
            commits_ingested=commits,
            pull_requests_ingested=prs,
            issues_ingested=issues,
            doc_changes_ingested=docs,
        )

    async def _ingest_kind_with_logging(
        self,
        context: _RepositoryIngestionContext,
        obs_context: IngestionRunContext,
        kind: typ.Literal["commit", "pull_request", "issue"],
    ) -> int:
        """Ingest a kind with observability logging."""
        result = await self._ingest_kind(context, kind=kind)
        stream_result = self._get_last_stream_result(context.offsets, kind)
        self._log_stream_result(obs_context, kind, result, stream_result)
        return result

    async def _ingest_doc_changes_with_logging(
        self,
        context: _RepositoryIngestionContext,
        obs_context: IngestionRunContext,
    ) -> int:
        """Ingest doc changes with observability logging."""
        result = await self._ingest_doc_changes(context)
        # Check if doc stream was truncated by looking at the cursor
        has_cursor = context.offsets.last_doc_cursor is not None
        if has_cursor:
            self._event_logger.log_stream_truncated(
                obs_context,
                StreamTruncationDetails(
                    kind="doc_change",
                    events_processed=self._config.max_events_per_kind,
                    max_events=self._config.max_events_per_kind,
                    resume_cursor=context.offsets.last_doc_cursor,
                ),
            )
        self._event_logger.log_stream_completed(obs_context, "doc_change", result)
        return result

    def _get_last_stream_result(
        self,
        offsets: GithubIngestionOffset,
        kind: typ.Literal["commit", "pull_request", "issue"],
    ) -> bool:
        """Check if the stream was truncated by looking at cursor state."""
        cursor_attr = _KIND_CURSOR_ATTR[kind]
        return getattr(offsets, cursor_attr) is not None

    def _log_stream_result(
        self,
        obs_context: IngestionRunContext,
        kind: str,
        ingested: int,
        was_truncated: bool,  # noqa: FBT001
    ) -> None:
        """Log stream completion or truncation."""
        if was_truncated:
            cursor_attr = _KIND_CURSOR_ATTR.get(
                typ.cast("typ.Literal['commit', 'pull_request', 'issue']", kind)
            )
            self._event_logger.log_stream_truncated(
                obs_context,
                StreamTruncationDetails(
                    kind=kind,
                    events_processed=self._config.max_events_per_kind,
                    max_events=self._config.max_events_per_kind,
                    resume_cursor=cursor_attr,
                ),
            )
        self._event_logger.log_stream_completed(obs_context, kind, ingested)

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
        self._update_doc_watermarks(offsets, result, resuming)
        return result.ingested

    def _update_doc_watermarks(
        self,
        offsets: GithubIngestionOffset,
        result: _StreamIngestionResult,
        resuming: bool,  # noqa: FBT001
    ) -> None:
        """Update doc change watermarks based on ingestion result."""
        self._update_stream_watermarks(
            offsets,
            attrs=_DOC_WATERMARK_ATTRS,
            result=result,
            resuming=resuming,
        )

    def _update_stream_watermarks(
        self,
        offsets: GithubIngestionOffset,
        *,
        attrs: _WatermarkAttrs,
        result: _StreamIngestionResult,
        resuming: bool,
    ) -> None:
        """Update offsets for a kind/doc ingestion stream."""
        setattr(offsets, attrs.cursor, result.resume_cursor)
        if result.truncated:
            setattr(
                offsets,
                attrs.seen,
                _max_dt(
                    typ.cast("dt.datetime | None", getattr(offsets, attrs.seen)),
                    result.max_seen,
                ),
            )
            return

        setattr(offsets, attrs.cursor, None)
        if not resuming:
            if result.max_seen is not None:
                setattr(offsets, attrs.watermark, result.max_seen)
            return

        previous_seen = typ.cast("dt.datetime | None", getattr(offsets, attrs.seen))
        final_seen = previous_seen or result.max_seen
        if final_seen is not None:
            setattr(offsets, attrs.watermark, final_seen)
        setattr(offsets, attrs.seen, None)

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
        self._update_kind_watermarks(
            offsets,
            kind=kind,
            result=result,
            resuming=resuming,
        )
        return result.ingested

    def _update_kind_watermarks(
        self,
        offsets: GithubIngestionOffset,
        *,
        kind: typ.Literal["commit", "pull_request", "issue"],
        result: _StreamIngestionResult,
        resuming: bool,
    ) -> None:
        """Update ingestion watermarks/cursors for a single entity kind."""
        watermark_attr = _KIND_WATERMARK_ATTR[kind]
        seen_attr = _KIND_SEEN_ATTR[kind]
        cursor_attr = _KIND_CURSOR_ATTR[kind]
        self._update_stream_watermarks(
            offsets,
            attrs=_WatermarkAttrs(
                cursor=cursor_attr,
                seen=seen_attr,
                watermark=watermark_attr,
            ),
            result=result,
            resuming=resuming,
        )

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
            last_cursor = event.cursor
            if max_seen is None or event.occurred_at > max_seen:
                max_seen = event.occurred_at
            if noise.should_drop(event):
                continue

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
        except (OperationalError, InterfaceError) as exc:
            logger.warning(
                (
                    "Failed to load noise filters for repo %s due to DB connectivity "
                    "issue; defaulting to no noise filters."
                ),
                repo.slug,
                exc_info=exc,
            )
            rows = []
        except SQLAlchemyError:
            logger.exception(
                (
                    "Failed to load noise filters for repo %s due to SQLAlchemy error; "
                    "failing ingestion."
                ),
                repo.slug,
            )
            raise

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
