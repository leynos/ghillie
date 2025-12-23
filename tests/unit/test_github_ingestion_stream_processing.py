"""Unit tests for low-level GitHub ingestion stream processing."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest

from ghillie.bronze import RawEventWriter
from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker
from ghillie.github.ingestion import _StreamIngestionResult
from ghillie.github.noise import CompiledNoiseFilters
from tests.unit.github_ingestion_test_helpers import (
    EventSpec,
    FakeGitHubClient,
    make_commit_events_with_cursors,
    make_event,
    make_repo_info,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.github.models import GitHubIngestedEvent


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
        repo,
        RawEventWriter(session_factory),
        _events(),
        noise=CompiledNoiseFilters(),
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
        repo,
        RawEventWriter(session_factory),
        _events(),
        noise=CompiledNoiseFilters(),
    )
    assert result.ingested == limit
    assert result.truncated is True
    assert result.resume_cursor == "cursor-2"
    assert result.max_seen == newest


@pytest.mark.asyncio
async def test_ingest_events_stream_advances_cursors_for_dropped_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Dropped events still advance max_seen and resume_cursor tracking."""
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
    events = [
        make_event(
            occurred_at=occurred_at,
            spec=EventSpec(
                event_type="github.commit",
                source_event_id=sha,
                payload={
                    "sha": sha,
                    "repo_owner": repo.owner,
                    "repo_name": repo.name,
                    "default_branch": repo.default_branch,
                    "committed_at": occurred_at.isoformat(),
                    "author_name": "dependabot[bot]",
                },
                cursor=cursor,
            ),
        )
        for sha, occurred_at, cursor in [
            ("e3", newest, "cursor-3"),
            ("e2", middle, "cursor-2"),
            ("e1", oldest, "cursor-1"),
        ]
    ]

    async def _events() -> typ.AsyncIterator[GitHubIngestedEvent]:
        for event in events:
            yield event

    result = await worker._ingest_events_stream(
        repo,
        RawEventWriter(session_factory),
        _events(),
        noise=CompiledNoiseFilters(ignore_authors=frozenset({"dependabot[bot]"})),
    )
    assert result.ingested == 0
    assert result.truncated is True
    assert result.resume_cursor == "cursor-2"
    assert result.max_seen == newest
