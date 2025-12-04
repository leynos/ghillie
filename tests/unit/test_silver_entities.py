"""Unit tests for Silver entity transformers."""

from __future__ import annotations

import asyncio
import dataclasses as dc
import datetime as dt
import typing as typ

from sqlalchemy import func, select

from ghillie.bronze import RawEventEnvelope, RawEventWriter
from ghillie.silver import (
    Commit,
    DocumentationChange,
    Issue,
    PullRequest,
    RawEventTransformer,
    Repository,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dc.dataclass(slots=True)
class CommitEventConfig:
    """Configuration for creating commit event envelopes."""

    repo_slug: str
    commit_sha: str
    occurred_at: dt.datetime
    source_event_id: str = "commit-1"
    message: str = "initial commit"
    committed_at: str = "2024-07-02T09:30:00Z"
    metadata: dict[str, object] | None = None


@dc.dataclass(slots=True)
class DocChangeEventConfig:
    """Configuration for creating documentation change event envelopes."""

    repo_slug: str
    commit_sha: str
    occurred_at: dt.datetime
    source_event_id: str
    occurred_at_str: str
    summary: str
    is_roadmap: bool = True
    is_adr: bool = False


@dc.dataclass(slots=True)
class PullRequestState:
    """Configuration for creating pull request payloads."""

    pr_id: int
    number: int
    state: str
    created_at: str
    merged_at: str | None
    closed_at: str | None
    labels: list[str] = dc.field(default_factory=list)
    metadata: dict[str, object] = dc.field(default_factory=dict)


def _run_async[T](coro_func: typ.Callable[[], typ.Coroutine[typ.Any, typ.Any, T]]) -> T:
    """Execute an async callable within the test context."""
    return asyncio.run(coro_func())


def _make_commit_event_envelope(config: CommitEventConfig) -> RawEventEnvelope:
    """Build a GitHub commit raw event envelope."""
    owner, name = config.repo_slug.split("/")
    return RawEventEnvelope(
        source_system="github",
        source_event_id=config.source_event_id,
        event_type="github.commit",
        repo_external_id=config.repo_slug,
        occurred_at=config.occurred_at,
        payload={
            "sha": config.commit_sha,
            "message": config.message,
            "author_email": "dev@example.com",
            "author_name": "Marina",
            "authored_at": "2024-07-02T09:15:00Z",
            "committed_at": config.committed_at,
            "repo_owner": owner,
            "repo_name": name,
            "default_branch": "main",
            "metadata": (
                config.metadata
                if config.metadata is not None
                else {"ref": "refs/heads/main"}
            ),
        },
    )


def _make_doc_change_event_envelope(
    config: DocChangeEventConfig,
) -> RawEventEnvelope:
    """Build a GitHub documentation change raw event envelope."""
    owner, name = config.repo_slug.split("/")
    return RawEventEnvelope(
        source_system="github",
        source_event_id=config.source_event_id,
        event_type="github.doc_change",
        repo_external_id=config.repo_slug,
        occurred_at=config.occurred_at,
        payload={
            "commit_sha": config.commit_sha,
            "path": "docs/roadmap.md",
            "change_type": "modified",
            "is_roadmap": config.is_roadmap,
            "is_adr": config.is_adr,
            "repo_owner": owner,
            "repo_name": name,
            "occurred_at": config.occurred_at_str,
            "metadata": {"summary": config.summary},
        },
    )


def test_commit_event_creates_repo_and_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Commit raw events populate repositories and commits tables."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    repo_owner = "octo"
    repo_name = "reef"
    commit_sha = "abc123"
    occurred_at = dt.datetime(2024, 7, 2, 9, 30, tzinfo=dt.UTC)

    async def _run() -> None:
        await writer.ingest(
            RawEventEnvelope(
                source_system="github",
                source_event_id="commit-1",
                event_type="github.commit",
                repo_external_id=f"{repo_owner}/{repo_name}",
                occurred_at=occurred_at,
                payload={
                    "sha": commit_sha,
                    "message": "initial commit",
                    "author_email": "dev@example.com",
                    "author_name": "Marina",
                    "authored_at": "2024-07-02T09:15:00Z",
                    "committed_at": "2024-07-02T09:30:00Z",
                    "repo_owner": repo_owner,
                    "repo_name": repo_name,
                    "default_branch": "main",
                    "metadata": {"ref": "refs/heads/main"},
                },
            )
        )
        await transformer.process_pending()

    _run_async(_run)

    async def _assert() -> None:
        async with session_factory() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == repo_owner,
                    Repository.github_name == repo_name,
                )
            )
            assert repo is not None
            assert repo.default_branch == "main"

            commit = await session.get(Commit, commit_sha)
            assert commit is not None
            assert commit.repo_id == repo.id
            assert commit.message == "initial commit"
            assert commit.author_email == "dev@example.com"
            assert commit.metadata_ == {"ref": "refs/heads/main"}
            assert commit.committed_at == dt.datetime(2024, 7, 2, 9, 30, tzinfo=dt.UTC)

    _run_async(_assert)


def _create_pr_payload(state: PullRequestState) -> dict[str, object]:
    """Build a pull request payload dict with the provided attributes."""
    return {
        "id": state.pr_id,
        "number": state.number,
        "title": "Add release checklist",
        "author_login": "marina",
        "state": state.state,
        "created_at": state.created_at,
        "merged_at": state.merged_at,
        "closed_at": state.closed_at,
        "labels": state.labels,
        "is_draft": False,
        "base_branch": "main",
        "head_branch": "feature/release-checklist",
        "repo_owner": "octo",
        "repo_name": "reef",
        "metadata": state.metadata,
    }


def _create_pr_envelope(
    *,
    event_id: str,
    repo_slug: str,
    occurred_at: dt.datetime,
    payload: dict[str, object],
) -> RawEventEnvelope:
    """Wrap a pull request payload into a RawEventEnvelope."""
    return RawEventEnvelope(
        source_system="github",
        source_event_id=event_id,
        event_type="github.pull_request",
        repo_external_id=repo_slug,
        occurred_at=occurred_at,
        payload=payload,
    )


def test_pull_request_events_update_existing_record(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Later pull request events update state without duplicating rows."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    repo_slug = "octo/reef"
    pr_id = 17
    occurred_open = dt.datetime(2024, 7, 3, 10, 0, tzinfo=dt.UTC)
    occurred_merge = dt.datetime(2024, 7, 3, 12, 0, tzinfo=dt.UTC)

    async def _run() -> None:
        await writer.ingest(
            _create_pr_envelope(
                event_id="pr-17-open",
                repo_slug=repo_slug,
                occurred_at=occurred_open,
                payload=_create_pr_payload(
                    PullRequestState(
                        pr_id=pr_id,
                        number=17,
                        state="open",
                        created_at="2024-07-03T10:00:00Z",
                        merged_at=None,
                        closed_at=None,
                        labels=["feature"],
                        metadata={"mergeable": "unknown"},
                    )
                ),
            )
        )
        await writer.ingest(
            _create_pr_envelope(
                event_id="pr-17-merged",
                repo_slug=repo_slug,
                occurred_at=occurred_merge,
                payload=_create_pr_payload(
                    PullRequestState(
                        pr_id=pr_id,
                        number=17,
                        state="merged",
                        created_at="2024-07-03T10:00:00Z",
                        merged_at="2024-07-03T12:00:00Z",
                        closed_at="2024-07-03T12:00:00Z",
                        labels=["feature", "ready-for-release"],
                        metadata={"merge_commit": "abc999"},
                    )
                ),
            )
        )
        await transformer.process_pending()

    _run_async(_run)

    async def _assert() -> None:
        async with session_factory() as session:
            pr = await session.get(PullRequest, pr_id)
            assert pr is not None
            assert pr.state == "merged"
            assert pr.merged_at == dt.datetime(2024, 7, 3, 12, 0, tzinfo=dt.UTC)
            assert pr.labels == ["feature", "ready-for-release"]
            assert pr.metadata_ == {"merge_commit": "abc999"}

            repo_count = await session.scalar(
                select(func.count()).select_from(Repository)
            )
            assert repo_count == 1

    _run_async(_assert)


def test_issue_event_creates_issue(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Issue events populate the issues table."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    repo_slug = "octo/reef"
    issue_id = 101
    occurred_at = dt.datetime(2024, 7, 4, 8, 45, tzinfo=dt.UTC)

    async def _run() -> None:
        await writer.ingest(
            RawEventEnvelope(
                source_system="github",
                source_event_id="issue-101",
                event_type="github.issue",
                repo_external_id=repo_slug,
                occurred_at=occurred_at,
                payload={
                    "id": issue_id,
                    "number": 101,
                    "title": "Fix flaky integration test",
                    "author_login": "qasquad",
                    "state": "open",
                    "created_at": "2024-07-04T08:45:00Z",
                    "closed_at": None,
                    "labels": ["bug", "infra"],
                    "repo_owner": "octo",
                    "repo_name": "reef",
                    "metadata": {"milestone": "MVP"},
                },
            )
        )
        await transformer.process_pending()

    _run_async(_run)

    async def _assert() -> None:
        async with session_factory() as session:
            issue = await session.get(Issue, issue_id)
            assert issue is not None
            assert issue.state == "open"
            assert issue.labels == ["bug", "infra"]
            assert issue.metadata_ == {"milestone": "MVP"}
            repo = await session.get(Repository, issue.repo_id)
            assert repo is not None

    _run_async(_assert)


def test_documentation_change_creates_stub_commit_when_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Doc change before a commit creates a stub commit and links to it."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    repo_slug = "octo/reef"
    commit_sha = "abcdef123456"
    occurred_at = dt.datetime(2024, 7, 5, 15, 0, tzinfo=dt.UTC)

    async def _run() -> None:
        await writer.ingest(
            _make_doc_change_event_envelope(
                DocChangeEventConfig(
                    repo_slug=repo_slug,
                    commit_sha=commit_sha,
                    occurred_at=occurred_at,
                    source_event_id="doc-change-stub",
                    occurred_at_str=occurred_at.isoformat(),
                    summary="readme tweak",
                    is_roadmap=False,
                    is_adr=False,
                )
            )
        )

        await transformer.process_pending()

        async with session_factory() as session:
            commit = await session.get(Commit, commit_sha)
            assert commit is not None
            repo = await session.get(Repository, commit.repo_id)
            assert repo is not None
            assert repo.github_owner == "octo"
            assert repo.github_name == "reef"
            assert commit.metadata_ == {}

            doc_changes = (
                await session.scalars(
                    select(DocumentationChange).where(
                        DocumentationChange.commit_sha == commit_sha
                    )
                )
            ).all()
            assert len(doc_changes) == 1
            assert doc_changes[0].path == "docs/roadmap.md"

    _run_async(_run)


def test_documentation_change_is_upserted_by_commit_and_path(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Documentation changes are deduplicated on commit+path and kept updated."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    repo_slug = "octo/reef"
    commit_sha = "abc123"
    occurred_at = dt.datetime(2024, 7, 5, 14, 0, tzinfo=dt.UTC)

    async def _run() -> None:
        await writer.ingest(
            _make_commit_event_envelope(
                CommitEventConfig(
                    repo_slug=repo_slug,
                    commit_sha=commit_sha,
                    occurred_at=occurred_at,
                    source_event_id="commit-doc",
                    message="docs: roadmap update",
                    committed_at="2024-07-05T13:55:00Z",
                )
            )
        )
        await writer.ingest(
            _make_doc_change_event_envelope(
                DocChangeEventConfig(
                    repo_slug=repo_slug,
                    commit_sha=commit_sha,
                    occurred_at=occurred_at,
                    source_event_id="doc-change-1",
                    occurred_at_str="2024-07-05T13:55:00Z",
                    summary="refresh milestones",
                )
            )
        )
        await writer.ingest(
            _make_doc_change_event_envelope(
                DocChangeEventConfig(
                    repo_slug=repo_slug,
                    commit_sha=commit_sha,
                    occurred_at=occurred_at,
                    source_event_id="doc-change-2",
                    occurred_at_str="2024-07-05T13:56:00Z",
                    summary="clarify deliverables",
                )
            )
        )
        await transformer.process_pending()

    _run_async(_run)

    async def _assert() -> None:
        async with session_factory() as session:
            doc_changes = (await session.scalars(select(DocumentationChange))).all()
            assert len(doc_changes) == 1
            doc_change = doc_changes[0]
            assert doc_change.commit_sha == commit_sha
            assert doc_change.path == "docs/roadmap.md"
            assert doc_change.metadata_ == {"summary": "clarify deliverables"}
            assert doc_change.occurred_at == dt.datetime(
                2024, 7, 5, 13, 56, tzinfo=dt.UTC
            )

    _run_async(_assert)
