"""Unit tests for the incremental GitHub ingestion worker."""

from __future__ import annotations

import dataclasses
import datetime as dt
import typing as typ

import pytest
from sqlalchemy import select

from ghillie.bronze import GithubIngestionOffset, RawEvent, RawEventWriter
from ghillie.github import GitHubIngestionConfig, GitHubIngestionWorker
from ghillie.github.ingestion import _StreamIngestionResult
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
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield commit events newer than `since`."""
        del repo
        start = 0
        if after is not None:
            for idx, event in enumerate(self._commits):
                if event.cursor == after:
                    start = idx + 1
                    break
        for event in self._commits[start:]:
            if event.occurred_at > since:
                yield event

    async def iter_pull_requests(
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield pull request events newer than `since`."""
        del repo, after
        for event in self._pull_requests:
            if event.occurred_at > since:
                yield event

    async def iter_issues(
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield issue events newer than `since`."""
        del repo, after
        for event in self._issues:
            if event.occurred_at > since:
                yield event

    async def iter_doc_changes(
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        documentation_paths: typ.Sequence[str],
        after: str | None = None,
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield documentation change events newer than `since`."""
        del repo, documentation_paths, after
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


def _disabled_repo_info() -> RepositoryInfo:
    return RepositoryInfo(
        id="repo-1",
        owner="octo",
        name="reef",
        default_branch="main",
        ingestion_enabled=False,
        documentation_paths=("docs/roadmap.md",),
        estate_id=None,
    )


def _event(  # noqa: PLR0913
    *,
    event_type: str,
    source_event_id: str,
    occurred_at: dt.datetime,
    payload: dict[str, object],
    cursor: str | None = None,
) -> GitHubIngestedEvent:
    return GitHubIngestedEvent(
        event_type=event_type,
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        payload=payload,
        cursor=cursor,
    )


def _create_test_commit_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test commit event for the ingestion worker."""
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


@dataclasses.dataclass(frozen=True, slots=True)
class _TestNumberedItemSpec:
    """Specification for creating a test numbered item event (PR or issue)."""

    event_type: str
    item_id: int
    title: str
    extra_fields: dict[str, object] | None = None


def _create_test_numbered_item_event(
    repo: RepositoryInfo,
    occurred_at: dt.datetime,
    spec: _TestNumberedItemSpec,
) -> GitHubIngestedEvent:
    """Create a numbered-item event (PR or issue) with shared payload fields."""
    payload: dict[str, object] = {
        "id": spec.item_id,
        "number": spec.item_id,
        "title": spec.title,
        "state": "open",
        "repo_owner": repo.owner,
        "repo_name": repo.name,
        "created_at": occurred_at.isoformat(),
    }
    if spec.extra_fields is not None:
        payload.update(spec.extra_fields)
    return _event(
        event_type=spec.event_type,
        source_event_id=str(spec.item_id),
        occurred_at=occurred_at,
        payload=payload,
    )


def _create_test_pr_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test pull request event for the ingestion worker."""
    spec = _TestNumberedItemSpec(
        event_type="github.pull_request",
        item_id=17,
        title="Add release checklist",
        extra_fields={
            "base_branch": "main",
            "head_branch": "feature/release-checklist",
        },
    )
    return _create_test_numbered_item_event(repo, occurred_at, spec)


def _create_test_issue_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test issue event for the ingestion worker."""
    spec = _TestNumberedItemSpec(
        event_type="github.issue",
        item_id=101,
        title="Fix flaky integration test",
        extra_fields=None,
    )
    return _create_test_numbered_item_event(repo, occurred_at, spec)


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


@pytest.mark.asyncio
async def test_ingestion_preserves_backlog_when_kind_limit_is_hit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Worker resumes pagination so older events are not skipped."""
    repo = _repo_info()
    now = dt.datetime.now(dt.UTC)
    newest = now - dt.timedelta(hours=1)
    middle = now - dt.timedelta(hours=2)
    oldest = now - dt.timedelta(hours=3)

    client = FakeGitHubClient(
        commits=[
            _event(
                event_type="github.commit",
                source_event_id="c3",
                occurred_at=newest,
                payload={
                    "sha": "c3",
                    "repo_owner": repo.owner,
                    "repo_name": repo.name,
                    "default_branch": repo.default_branch,
                    "committed_at": newest.isoformat(),
                },
                cursor="cursor-3",
            ),
            _event(
                event_type="github.commit",
                source_event_id="c2",
                occurred_at=middle,
                payload={
                    "sha": "c2",
                    "repo_owner": repo.owner,
                    "repo_name": repo.name,
                    "default_branch": repo.default_branch,
                    "committed_at": middle.isoformat(),
                },
                cursor="cursor-2",
            ),
            _event(
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
    repo = _disabled_repo_info()
    occurred_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10)
    client = FakeGitHubClient(
        commits=[_create_test_commit_event(repo, occurred_at)],
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
        assert (await session.scalars(select(RawEvent.id))).all() == []
        offsets = await session.scalar(select(GithubIngestionOffset))
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
    repo = _repo_info()
    worker = GitHubIngestionWorker(
        session_factory,
        FakeGitHubClient(commits=[], pull_requests=[], issues=[], doc_changes=[]),
        config=GitHubIngestionConfig(max_events_per_kind=2),
    )

    async def _events() -> typ.AsyncIterator[GitHubIngestedEvent]:
        if False:  # pragma: no cover
            yield GitHubIngestedEvent(
                event_type="github.commit",
                source_event_id="never",
                occurred_at=dt.datetime.now(dt.UTC),
                payload={},
            )

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
    repo = _repo_info()
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
        _event(
            event_type="github.commit",
            source_event_id="e3",
            occurred_at=newest,
            payload={
                "sha": "e3",
                "repo_owner": repo.owner,
                "repo_name": repo.name,
                "default_branch": repo.default_branch,
                "committed_at": newest.isoformat(),
            },
            cursor="cursor-3",
        ),
        _event(
            event_type="github.commit",
            source_event_id="e2",
            occurred_at=middle,
            payload={
                "sha": "e2",
                "repo_owner": repo.owner,
                "repo_name": repo.name,
                "default_branch": repo.default_branch,
                "committed_at": middle.isoformat(),
            },
            cursor="cursor-2",
        ),
        _event(
            event_type="github.commit",
            source_event_id="e1",
            occurred_at=oldest,
            payload={
                "sha": "e1",
                "repo_owner": repo.owner,
                "repo_name": repo.name,
                "default_branch": repo.default_branch,
                "committed_at": oldest.isoformat(),
            },
            cursor="cursor-1",
        ),
    ]

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
    repo = _repo_info()
    now = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    newest = now - dt.timedelta(hours=1)
    oldest = now - dt.timedelta(hours=2)
    client = FakeGitHubClient(
        commits=[
            _event(
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
            _event(
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
    await worker._ingest_kind(repo, writer, offsets, kind="commit", now=now)
    assert offsets.last_commit_cursor == "cursor-2"
    assert offsets.last_commit_ingested_at is None

    await worker._ingest_kind(repo, writer, offsets, kind="commit", now=now)
    assert offsets.last_commit_cursor is None
    assert offsets.last_commit_ingested_at == newest
