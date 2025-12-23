"""Unit tests for GitHub ingestion pagination and backlog preservation."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest
from sqlalchemy import select

from ghillie.bronze import GithubIngestionOffset, RawEvent, RawEventWriter
from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker
from ghillie.github.ingestion import _RepositoryIngestionContext
from ghillie.github.noise import CompiledNoiseFilters
from tests.unit.github_ingestion_test_helpers import (
    FakeGitHubClient,
    make_commit_events_with_cursors,
    make_repo_info,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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
    commits = make_commit_events_with_cursors(
        repo,
        [
            ("c2", newest, "cursor-2"),
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
            max_events_per_kind=1,
        ),
    )
    offsets = await worker._load_or_create_offsets(repo.slug)
    writer = RawEventWriter(session_factory)
    context = _RepositoryIngestionContext(
        repo=repo,
        writer=writer,
        offsets=offsets,
        noise=CompiledNoiseFilters(),
        now=now,
    )
    await worker._ingest_kind(context, kind="commit")
    assert offsets.last_commit_cursor == "cursor-2"
    assert offsets.last_commit_ingested_at is None

    await worker._ingest_kind(context, kind="commit")
    assert offsets.last_commit_cursor is None
    assert offsets.last_commit_ingested_at == newest
