"""Unit tests for the incremental GitHub ingestion worker."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest
from sqlalchemy import select

from ghillie.bronze import GithubIngestionOffset, RawEvent, RawEventWriter
from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker

# These tests intentionally cover internal ingestion primitives and cursor/watermark
# edge cases to prevent regressions in backlog preservation behaviour.
from ghillie.github.ingestion import _KindIngestionContext, _StreamIngestionResult
from tests.unit.github_ingestion_test_helpers import (
    FakeGitHubClient,
    make_commit_event,
    make_commit_events_with_cursors,
    make_disabled_repo_info,
    make_doc_change_event,
    make_event,
    make_issue_event,
    make_pr_event,
    make_repo_info,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.github.models import GitHubIngestedEvent


@pytest.mark.asyncio
async def test_ingestion_writes_raw_events_and_updates_watermarks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Worker writes raw events and stores per-kind watermarks."""
    repo = make_repo_info()
    now = dt.datetime.now(dt.UTC)
    commit_time = now - dt.timedelta(hours=4)
    pr_time = now - dt.timedelta(hours=3)
    issue_time = now - dt.timedelta(hours=2)
    doc_time = now - dt.timedelta(hours=1)

    client = FakeGitHubClient(
        commits=[make_commit_event(repo, commit_time)],
        pull_requests=[make_pr_event(repo, pr_time)],
        issues=[make_issue_event(repo, issue_time)],
        doc_changes=[make_doc_change_event(repo, doc_time)],
    )
    worker = GitHubIngestionWorker(
        session_factory,
        client,
        config=GitHubIngestionConfig(
            overlap=dt.timedelta(0),
            initial_lookback=dt.timedelta(days=1),
        ),
    )

    result = await worker.ingest_repository(repo)
    assert result.commits_ingested == 1
    assert result.pull_requests_ingested == 1
    assert result.issues_ingested == 1
    assert result.doc_changes_ingested == 1

    async with session_factory() as session:
        expected_total = 4
        raw_events = (await session.scalars(select(RawEvent))).all()
        assert len(raw_events) == expected_total
        offsets = await session.scalar(
            select(GithubIngestionOffset).where(
                GithubIngestionOffset.repo_external_id == repo.slug
            )
        )
        assert offsets is not None
        assert offsets.last_commit_ingested_at == commit_time
        assert offsets.last_pr_ingested_at == pr_time
        assert offsets.last_issue_ingested_at == issue_time
        assert offsets.last_doc_ingested_at == doc_time


@pytest.mark.asyncio
async def test_ingestion_is_idempotent_for_unchanged_activity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Re-running ingestion does not duplicate unchanged raw events."""
    repo = make_repo_info()
    occurred_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10)
    event = make_event(
        event_type="github.commit",
        source_event_id="abc999",
        occurred_at=occurred_at,
        payload={
            "sha": "abc999",
            "repo_owner": repo.owner,
            "repo_name": repo.name,
            "default_branch": repo.default_branch,
            "committed_at": occurred_at.isoformat(),
        },
    )
    client = FakeGitHubClient(
        commits=[event], pull_requests=[], issues=[], doc_changes=[]
    )
    worker = GitHubIngestionWorker(
        session_factory,
        client,
        config=GitHubIngestionConfig(
            overlap=dt.timedelta(0),
            initial_lookback=dt.timedelta(days=1),
        ),
    )

    await worker.ingest_repository(repo)
    await worker.ingest_repository(repo)

    async with session_factory() as session:
        ids = (await session.scalars(select(RawEvent.id))).all()
        assert len(ids) == 1


@pytest.mark.asyncio
async def test_ingestion_preserves_backlog_when_kind_limit_is_hit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Worker resumes pagination so older events are not skipped."""
    repo = make_repo_info()
    now = dt.datetime.now(dt.UTC)
    newest = now - dt.timedelta(hours=1)
    middle = now - dt.timedelta(hours=2)
    oldest = now - dt.timedelta(hours=3)

    commits = make_commit_events_with_cursors(
        repo,
        [
            ("c3", newest, "cursor-3"),
            ("c2", middle, "cursor-2"),
            ("c1", oldest, "cursor-1"),
        ],
    )
    client = FakeGitHubClient(
        commits=commits,
        pull_requests=[],
        issues=[],
        doc_changes=[],
    )
    worker = GitHubIngestionWorker(
        session_factory,
        client,
        config=GitHubIngestionConfig(
            overlap=dt.timedelta(0),
            initial_lookback=dt.timedelta(days=1),
            max_events_per_kind=2,
        ),
    )

    await worker.ingest_repository(repo)
    await worker.ingest_repository(repo)

    async with session_factory() as session:
        raw_events = (
            await session.scalars(
                select(RawEvent).where(RawEvent.repo_external_id == repo.slug)
            )
        ).all()
        assert {event.source_event_id for event in raw_events} == {"c1", "c2", "c3"}
        offsets = await session.scalar(
            select(GithubIngestionOffset).where(
                GithubIngestionOffset.repo_external_id == repo.slug
            )
        )
        assert offsets is not None
        assert offsets.last_commit_cursor is None
        assert offsets.last_commit_ingested_at == newest


@pytest.mark.asyncio
async def test_worker_skips_disabled_repository_without_side_effects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Disabled repositories do not write raw events or offsets."""
    repo = make_disabled_repo_info()
    occurred_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10)
    client = FakeGitHubClient(
        commits=[make_commit_event(repo, occurred_at)],
        pull_requests=[],
        issues=[],
        doc_changes=[],
    )
    worker = GitHubIngestionWorker(session_factory, client)

    result = await worker.ingest_repository(repo)
    assert result.commits_ingested == 0
    assert result.pull_requests_ingested == 0
    assert result.issues_ingested == 0
    assert result.doc_changes_ingested == 0

    async with session_factory() as session:
        raw_ids = (
            await session.scalars(
                select(RawEvent.id).where(RawEvent.repo_external_id == repo.slug)
            )
        ).all()
        assert raw_ids == []
        offsets = await session.scalar(
            select(GithubIngestionOffset).where(
                GithubIngestionOffset.repo_external_id == repo.slug
            )
        )
        assert offsets is None


@pytest.mark.asyncio
async def test_since_for_uses_initial_lookback_and_overlap(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """_since_for applies initial_lookback and overlap consistently."""
    worker = GitHubIngestionWorker(
        session_factory,
        FakeGitHubClient(commits=[], pull_requests=[], issues=[], doc_changes=[]),
        config=GitHubIngestionConfig(
            initial_lookback=dt.timedelta(days=7),
            overlap=dt.timedelta(minutes=5),
        ),
    )
    now = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert worker._since_for(None, now=now) == now - dt.timedelta(days=7, minutes=5)
    watermark = dt.datetime(2024, 12, 31, tzinfo=dt.UTC)
    assert worker._since_for(watermark, now=now) == watermark - dt.timedelta(minutes=5)


@pytest.mark.asyncio
async def test_ingest_events_stream_handles_empty_stream(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """_ingest_events_stream returns a neutral result when no events exist."""
    repo = make_repo_info()
    worker = GitHubIngestionWorker(
        session_factory,
        FakeGitHubClient(commits=[], pull_requests=[], issues=[], doc_changes=[]),
        config=GitHubIngestionConfig(max_events_per_kind=2),
    )

    async def _events() -> typ.AsyncIterator[GitHubIngestedEvent]:
        return
        yield  # type: ignore[misc]  # Makes this an async generator

    result = await worker._ingest_events_stream(
        repo, RawEventWriter(session_factory), _events()
    )
    assert isinstance(result, _StreamIngestionResult)
    assert result.ingested == 0
    assert result.max_seen is None
    assert result.resume_cursor is None
    assert result.truncated is False


@pytest.mark.asyncio
async def test_ingest_events_stream_sets_resume_cursor_when_truncated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """_ingest_events_stream captures the last ingested cursor on truncation."""
    limit = 2
    repo = make_repo_info()
    now = dt.datetime.now(dt.UTC)
    newest = now - dt.timedelta(minutes=1)
    middle = now - dt.timedelta(minutes=2)
    oldest = now - dt.timedelta(minutes=3)
    worker = GitHubIngestionWorker(
        session_factory,
        FakeGitHubClient(commits=[], pull_requests=[], issues=[], doc_changes=[]),
        config=GitHubIngestionConfig(max_events_per_kind=limit),
    )
    events = make_commit_events_with_cursors(
        repo,
        [
            ("e3", newest, "cursor-3"),
            ("e2", middle, "cursor-2"),
            ("e1", oldest, "cursor-1"),
        ],
    )

    async def _events() -> typ.AsyncIterator[GitHubIngestedEvent]:
        for event in events:
            yield event

    result = await worker._ingest_events_stream(
        repo, RawEventWriter(session_factory), _events()
    )
    assert result.ingested == limit
    assert result.truncated is True
    assert result.resume_cursor == "cursor-2"
    assert result.max_seen == newest


@pytest.mark.asyncio
async def test_ingest_kind_resumes_with_cursor_until_backlog_caught_up(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """_ingest_kind keeps the watermark stable while truncating.

    Once catch-up is complete, the kind watermark advances to the latest event
    that has been persisted.
    """
    repo = make_repo_info()
    now = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    newest = now - dt.timedelta(hours=1)
    oldest = now - dt.timedelta(hours=2)
    client = FakeGitHubClient(
        commits=[
            make_event(
                event_type="github.commit",
                source_event_id="c2",
                occurred_at=newest,
                payload={
                    "sha": "c2",
                    "repo_owner": repo.owner,
                    "repo_name": repo.name,
                    "default_branch": repo.default_branch,
                    "committed_at": newest.isoformat(),
                },
                cursor="cursor-2",
            ),
            make_event(
                event_type="github.commit",
                source_event_id="c1",
                occurred_at=oldest,
                payload={
                    "sha": "c1",
                    "repo_owner": repo.owner,
                    "repo_name": repo.name,
                    "default_branch": repo.default_branch,
                    "committed_at": oldest.isoformat(),
                },
                cursor="cursor-1",
            ),
        ],
        pull_requests=[],
        issues=[],
        doc_changes=[],
    )
    worker = GitHubIngestionWorker(
        session_factory,
        client,
        config=GitHubIngestionConfig(
            overlap=dt.timedelta(0),
            initial_lookback=dt.timedelta(days=1),
            max_events_per_kind=1,
        ),
    )
    offsets = await worker._load_or_create_offsets(repo.slug)
    writer = RawEventWriter(session_factory)
    await worker._ingest_kind(
        repo, writer, offsets, context=_KindIngestionContext(kind="commit", now=now)
    )
    assert offsets.last_commit_cursor == "cursor-2"
    assert offsets.last_commit_ingested_at is None

    await worker._ingest_kind(
        repo, writer, offsets, context=_KindIngestionContext(kind="commit", now=now)
    )
    assert offsets.last_commit_cursor is None
    assert offsets.last_commit_ingested_at == newest
