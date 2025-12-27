"""Unit tests for GitHub ingestion worker observability instrumentation."""

from __future__ import annotations

import datetime as dt
import logging
import typing as typ

import pytest

from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker
from ghillie.github.errors import GitHubAPIError
from ghillie.github.models import GitHubIngestedEvent
from ghillie.github.observability import IngestionEventType
from tests.unit.github_ingestion_test_helpers import (
    FailingGitHubClient,
    FakeGitHubClient,
    make_commit_event,
    make_commit_events_with_cursors,
    make_disabled_repo_info,
    make_doc_change_event,
    make_issue_event,
    make_pr_event,
    make_repo_info,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_worker_logs_run_started_and_completed(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Worker logs run started and completed events for successful ingestion."""
    repo = make_repo_info()
    now = dt.datetime.now(dt.UTC)
    commit_time = now - dt.timedelta(hours=1)

    client = FakeGitHubClient(
        commits=[make_commit_event(repo, commit_time)],
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
        ),
    )

    with caplog.at_level(logging.INFO, logger="ghillie.github.observability"):
        await worker.ingest_repository(repo)

    # Check for RUN_STARTED event
    started_records = [
        r for r in caplog.records if IngestionEventType.RUN_STARTED in r.message
    ]
    assert len(started_records) == 1
    assert repo.slug in started_records[0].message

    # Check for RUN_COMPLETED event
    completed_records = [
        r for r in caplog.records if IngestionEventType.RUN_COMPLETED in r.message
    ]
    assert len(completed_records) == 1
    assert repo.slug in completed_records[0].message
    assert "commits_ingested=1" in completed_records[0].message
    assert "duration_seconds=" in completed_records[0].message


@pytest.mark.asyncio
async def test_worker_logs_run_failed_on_exception(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Worker logs run failed event when ingestion raises an exception."""
    repo = make_repo_info()

    client = FailingGitHubClient(GitHubAPIError.http_error(502))
    worker = GitHubIngestionWorker(
        session_factory,
        client,
        config=GitHubIngestionConfig(
            overlap=dt.timedelta(0),
            initial_lookback=dt.timedelta(days=1),
        ),
    )

    with (
        caplog.at_level(logging.ERROR, logger="ghillie.github.observability"),
        pytest.raises(GitHubAPIError),
    ):
        await worker.ingest_repository(repo)

    # Check for RUN_FAILED event
    failed_records = [
        r for r in caplog.records if IngestionEventType.RUN_FAILED in r.message
    ]
    assert len(failed_records) == 1
    assert repo.slug in failed_records[0].message
    assert "error_type=GitHubAPIError" in failed_records[0].message
    assert "error_category=transient" in failed_records[0].message


@pytest.mark.asyncio
async def test_worker_logs_stream_completed_for_each_kind(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Worker logs stream completed events for each ingested kind."""
    repo = make_repo_info()
    now = dt.datetime.now(dt.UTC)

    client = FakeGitHubClient(
        commits=[make_commit_event(repo, now - dt.timedelta(hours=4))],
        pull_requests=[make_pr_event(repo, now - dt.timedelta(hours=3))],
        issues=[make_issue_event(repo, now - dt.timedelta(hours=2))],
        doc_changes=[make_doc_change_event(repo, now - dt.timedelta(hours=1))],
    )
    worker = GitHubIngestionWorker(
        session_factory,
        client,
        config=GitHubIngestionConfig(
            overlap=dt.timedelta(0),
            initial_lookback=dt.timedelta(days=1),
        ),
    )

    with caplog.at_level(logging.INFO, logger="ghillie.github.observability"):
        await worker.ingest_repository(repo)

    stream_records = [
        r for r in caplog.records if IngestionEventType.STREAM_COMPLETED in r.message
    ]
    # Should have 4 stream completed events: commit, pull_request, issue, doc_change
    assert len(stream_records) == 4

    kinds_logged = [r.message for r in stream_records]
    assert any("stream_kind=commit" in m for m in kinds_logged)
    assert any("stream_kind=pull_request" in m for m in kinds_logged)
    assert any("stream_kind=issue" in m for m in kinds_logged)
    assert any("stream_kind=doc_change" in m for m in kinds_logged)


@pytest.mark.asyncio
async def test_disabled_repository_does_not_emit_observability_events(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Disabled repositories skip observability logging."""
    repo = make_disabled_repo_info()

    client = FakeGitHubClient(
        commits=[],
        pull_requests=[],
        issues=[],
        doc_changes=[],
    )
    worker = GitHubIngestionWorker(session_factory, client)

    with caplog.at_level(logging.INFO, logger="ghillie.github.observability"):
        await worker.ingest_repository(repo)

    # No observability events should be logged for disabled repos
    obs_records = [
        r
        for r in caplog.records
        if "ingestion.run" in r.message or "ingestion.stream" in r.message
    ]
    assert len(obs_records) == 0


@pytest.mark.asyncio
async def test_worker_logs_completed_with_zero_events(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Worker logs completion even when no events are ingested."""
    repo = make_repo_info()

    client = FakeGitHubClient(
        commits=[],
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
        ),
    )

    with caplog.at_level(logging.INFO, logger="ghillie.github.observability"):
        await worker.ingest_repository(repo)

    completed_records = [
        r for r in caplog.records if IngestionEventType.RUN_COMPLETED in r.message
    ]
    assert len(completed_records) == 1
    assert "total_events=0" in completed_records[0].message


@pytest.mark.asyncio
async def test_worker_logs_estate_id_when_present(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Worker includes estate_id in observability logs when present."""
    repo = make_repo_info(estate_id="wildside")

    client = FakeGitHubClient(
        commits=[],
        pull_requests=[],
        issues=[],
        doc_changes=[],
    )
    worker = GitHubIngestionWorker(session_factory, client)

    with caplog.at_level(logging.INFO, logger="ghillie.github.observability"):
        await worker.ingest_repository(repo)

    started_records = [
        r for r in caplog.records if IngestionEventType.RUN_STARTED in r.message
    ]
    assert len(started_records) == 1
    assert "estate_id=wildside" in started_records[0].message


@pytest.mark.asyncio
async def test_worker_logs_stream_truncated_for_kind(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Worker logs STREAM_TRUNCATED when max_events_per_kind is exceeded."""
    repo = make_repo_info()
    now = dt.datetime.now(dt.UTC)

    # Create more commits than max_events_per_kind allows (with cursors for truncation)
    commits = make_commit_events_with_cursors(
        repo,
        [(f"sha{i}", now - dt.timedelta(minutes=i), f"cursor{i}") for i in range(5)],
    )
    client = FakeGitHubClient(
        commits=commits,
        pull_requests=[],
        issues=[],
        doc_changes=[],
    )
    # Use low max_events_per_kind to trigger truncation
    worker = GitHubIngestionWorker(
        session_factory,
        client,
        config=GitHubIngestionConfig(
            overlap=dt.timedelta(0),
            initial_lookback=dt.timedelta(days=1),
            max_events_per_kind=2,
        ),
    )

    with caplog.at_level(logging.WARNING, logger="ghillie.github.observability"):
        await worker.ingest_repository(repo)

    # Check for STREAM_TRUNCATED event for commits
    truncated_records = [
        r for r in caplog.records if IngestionEventType.STREAM_TRUNCATED in r.message
    ]
    assert len(truncated_records) >= 1, "Expected at least one STREAM_TRUNCATED event"

    commit_truncated = [
        r for r in truncated_records if "stream_kind=commit" in r.message
    ]
    assert len(commit_truncated) == 1, "Expected STREAM_TRUNCATED for commit stream"
    assert "events_processed=2" in commit_truncated[0].message
    assert "max_events=2" in commit_truncated[0].message
    assert "has_resume_cursor=True" in commit_truncated[0].message


@pytest.mark.asyncio
async def test_worker_logs_stream_truncated_for_doc_changes(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Worker logs STREAM_TRUNCATED for doc changes when truncated."""
    repo = make_repo_info()
    now = dt.datetime.now(dt.UTC)

    # Create more doc changes than max_events_per_kind allows (with cursors)
    doc_changes = [
        GitHubIngestedEvent(
            event_type="github.doc_change",
            source_event_id=f"sha{i}:docs/file{i}.md",
            occurred_at=now - dt.timedelta(minutes=i),
            payload={
                "commit_sha": f"sha{i}",
                "path": f"docs/file{i}.md",
                "change_type": "modified",
                "repo_owner": repo.owner,
                "repo_name": repo.name,
                "occurred_at": (now - dt.timedelta(minutes=i)).isoformat(),
            },
            cursor=f"doc_cursor{i}",
        )
        for i in range(5)
    ]
    client = FakeGitHubClient(
        commits=[],
        pull_requests=[],
        issues=[],
        doc_changes=doc_changes,
    )
    # Use low max_events_per_kind to trigger truncation
    worker = GitHubIngestionWorker(
        session_factory,
        client,
        config=GitHubIngestionConfig(
            overlap=dt.timedelta(0),
            initial_lookback=dt.timedelta(days=1),
            max_events_per_kind=2,
        ),
    )

    with caplog.at_level(logging.WARNING, logger="ghillie.github.observability"):
        await worker.ingest_repository(repo)

    # Check for STREAM_TRUNCATED event for doc_change
    truncated_records = [
        r for r in caplog.records if IngestionEventType.STREAM_TRUNCATED in r.message
    ]
    doc_truncated = [
        r for r in truncated_records if "stream_kind=doc_change" in r.message
    ]
    assert len(doc_truncated) == 1, "Expected STREAM_TRUNCATED for doc_change stream"
    assert "events_processed=2" in doc_truncated[0].message
    assert "max_events=2" in doc_truncated[0].message
    assert "has_resume_cursor=True" in doc_truncated[0].message


@pytest.mark.asyncio
async def test_worker_no_truncation_when_under_limit(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Worker does not log STREAM_TRUNCATED when events are under the limit."""
    repo = make_repo_info()
    now = dt.datetime.now(dt.UTC)

    # Create fewer commits than max_events_per_kind
    commits = [make_commit_event(repo, now - dt.timedelta(minutes=i)) for i in range(2)]
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
            max_events_per_kind=10,  # Higher than number of events
        ),
    )

    with caplog.at_level(logging.WARNING, logger="ghillie.github.observability"):
        await worker.ingest_repository(repo)

    # No STREAM_TRUNCATED events should be logged
    truncated_records = [
        r for r in caplog.records if IngestionEventType.STREAM_TRUNCATED in r.message
    ]
    assert len(truncated_records) == 0, "Expected no STREAM_TRUNCATED events"
