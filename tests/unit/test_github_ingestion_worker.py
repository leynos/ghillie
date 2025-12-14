"""Unit tests for the incremental GitHub ingestion worker."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest
from sqlalchemy import select

from ghillie.bronze import GithubIngestionOffset, RawEvent
from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker
from ghillie.github.models import GitHubIngestedEvent
from ghillie.registry.models import RepositoryInfo

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class FakeGitHubClient:
    """Deterministic GitHubActivityClient implementation for tests."""

    def __init__(
        self,
        *,
        commits: list[GitHubIngestedEvent],
        pull_requests: list[GitHubIngestedEvent],
        issues: list[GitHubIngestedEvent],
        doc_changes: list[GitHubIngestedEvent],
    ) -> None:
        """Store event lists returned by iterator methods."""
        self._commits = commits
        self._pull_requests = pull_requests
        self._issues = issues
        self._doc_changes = doc_changes

    async def iter_commits(
        self, repo: RepositoryInfo, *, since: dt.datetime
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield commit events newer than `since`."""
        for event in self._commits:
            if event.occurred_at > since:
                yield event

    async def iter_pull_requests(
        self, repo: RepositoryInfo, *, since: dt.datetime
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield pull request events newer than `since`."""
        for event in self._pull_requests:
            if event.occurred_at > since:
                yield event

    async def iter_issues(
        self, repo: RepositoryInfo, *, since: dt.datetime
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield issue events newer than `since`."""
        for event in self._issues:
            if event.occurred_at > since:
                yield event

    async def iter_doc_changes(
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        documentation_paths: typ.Sequence[str],
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield documentation change events newer than `since`."""
        del documentation_paths
        for event in self._doc_changes:
            if event.occurred_at > since:
                yield event


def _repo_info() -> RepositoryInfo:
    return RepositoryInfo(
        id="repo-1",
        owner="octo",
        name="reef",
        default_branch="main",
        ingestion_enabled=True,
        documentation_paths=("docs/roadmap.md",),
        estate_id=None,
    )


def _event(
    *,
    event_type: str,
    source_event_id: str,
    occurred_at: dt.datetime,
    payload: dict[str, object],
) -> GitHubIngestedEvent:
    return GitHubIngestedEvent(
        event_type=event_type,
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        payload=payload,
    )


def _create_test_commit_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    return _event(
        event_type="github.commit",
        source_event_id="abc123",
        occurred_at=occurred_at,
        payload={
            "sha": "abc123",
            "repo_owner": repo.owner,
            "repo_name": repo.name,
            "default_branch": repo.default_branch,
            "committed_at": occurred_at.isoformat(),
        },
    )


def _create_test_pr_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    return _event(
        event_type="github.pull_request",
        source_event_id="17",
        occurred_at=occurred_at,
        payload={
            "id": 17,
            "number": 17,
            "title": "Add release checklist",
            "state": "open",
            "base_branch": "main",
            "head_branch": "feature/release-checklist",
            "repo_owner": repo.owner,
            "repo_name": repo.name,
            "created_at": occurred_at.isoformat(),
        },
    )


def _create_test_issue_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    return _event(
        event_type="github.issue",
        source_event_id="101",
        occurred_at=occurred_at,
        payload={
            "id": 101,
            "number": 101,
            "title": "Fix flaky integration test",
            "state": "open",
            "repo_owner": repo.owner,
            "repo_name": repo.name,
            "created_at": occurred_at.isoformat(),
        },
    )


def _create_test_doc_change_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    return _event(
        event_type="github.doc_change",
        source_event_id="abc123:docs/roadmap.md",
        occurred_at=occurred_at,
        payload={
            "commit_sha": "abc123",
            "path": "docs/roadmap.md",
            "change_type": "modified",
            "repo_owner": repo.owner,
            "repo_name": repo.name,
            "occurred_at": occurred_at.isoformat(),
            "is_roadmap": True,
            "is_adr": False,
        },
    )


@pytest.mark.asyncio
async def test_ingestion_writes_raw_events_and_updates_watermarks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Worker writes raw events and stores per-kind watermarks."""
    repo = _repo_info()
    now = dt.datetime.now(dt.UTC)
    commit_time = now - dt.timedelta(hours=4)
    pr_time = now - dt.timedelta(hours=3)
    issue_time = now - dt.timedelta(hours=2)
    doc_time = now - dt.timedelta(hours=1)

    client = FakeGitHubClient(
        commits=[_create_test_commit_event(repo, commit_time)],
        pull_requests=[_create_test_pr_event(repo, pr_time)],
        issues=[_create_test_issue_event(repo, issue_time)],
        doc_changes=[_create_test_doc_change_event(repo, doc_time)],
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
    repo = _repo_info()
    occurred_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10)
    event = _event(
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
        commits=[event],
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

    await worker.ingest_repository(repo)
    await worker.ingest_repository(repo)

    async with session_factory() as session:
        ids = (await session.scalars(select(RawEvent.id))).all()
        assert len(ids) == 1
