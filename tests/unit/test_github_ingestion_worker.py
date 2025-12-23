"""Unit tests for the core GitHub ingestion worker."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest
from sqlalchemy import select

from ghillie.bronze import GithubIngestionOffset, RawEvent
from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker
from tests.unit.github_ingestion_test_helpers import (
    EventSpec,
    FakeGitHubClient,
    make_commit_event,
    make_disabled_repo_info,
    make_doc_change_event,
    make_event,
    make_issue_event,
    make_pr_event,
    make_repo_info,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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
        occurred_at,
        EventSpec(
            event_type="github.commit",
            source_event_id="abc999",
            payload={
                "sha": "abc999",
                "repo_owner": repo.owner,
                "repo_name": repo.name,
                "default_branch": repo.default_branch,
                "committed_at": occurred_at.isoformat(),
            },
        ),
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
