"""Behavioural coverage for Silver entity table hydration."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

from pytest_bdd import given, scenario, then, when
from sqlalchemy import select

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


def _run_async[T](coro_func: typ.Callable[[], typ.Coroutine[typ.Any, typ.Any, T]]) -> T:
    """Execute an async callable within the test context."""
    return asyncio.run(coro_func())


class SilverContext(typ.TypedDict, total=False):
    """Shared mutable scenario state."""

    session_factory: async_sessionmaker[AsyncSession]
    writer: RawEventWriter
    transformer: RawEventTransformer
    repo_slug: str
    commit_sha: str


@scenario(
    "../silver_entities.feature",
    "GitHub entity events hydrate Silver tables",
)
def test_silver_entity_hydration() -> None:
    """Wrap the pytest-bdd scenario."""


@given(
    "an empty Bronze and Silver store for Silver entities",
    target_fixture="silver_context",
)
def given_empty_store(
    session_factory: async_sessionmaker[AsyncSession],
) -> SilverContext:
    """Provide a clean store for the scenario."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    return {
        "session_factory": session_factory,
        "writer": writer,
        "transformer": transformer,
        "repo_slug": "octo/reef",
        "commit_sha": "abc123",
    }


def _create_commit_event(
    repo_slug: str, commit_sha: str, occurred_at: dt.datetime
) -> RawEventEnvelope:
    """Build a commit RawEventEnvelope for the scenario."""
    return RawEventEnvelope(
        source_system="github",
        source_event_id="commit-silver",
        event_type="github.commit",
        repo_external_id=repo_slug,
        occurred_at=occurred_at,
        payload={
            "sha": commit_sha,
            "message": "docs: flesh out roadmap",
            "author_email": "marina@example.com",
            "author_name": "Marina",
            "authored_at": "2024-07-06T11:10:00Z",
            "committed_at": "2024-07-06T11:25:00Z",
            "repo_owner": "octo",
            "repo_name": "reef",
            "default_branch": "main",
            "metadata": {"ref": "refs/heads/main"},
        },
    )


def _create_pull_request_event(
    repo_slug: str, occurred_at: dt.datetime
) -> RawEventEnvelope:
    """Build a pull request RawEventEnvelope for the scenario."""
    return RawEventEnvelope(
        source_system="github",
        source_event_id="pr-silver",
        event_type="github.pull_request",
        repo_external_id=repo_slug,
        occurred_at=occurred_at,
        payload={
            "id": 17,
            "number": 17,
            "title": "Add quarterly roadmap",
            "author_login": "marina",
            "state": "merged",
            "created_at": "2024-07-05T15:00:00Z",
            "merged_at": "2024-07-06T10:55:00Z",
            "closed_at": "2024-07-06T10:55:00Z",
            "labels": ["feature", "roadmap"],
            "is_draft": False,
            "base_branch": "main",
            "head_branch": "feature/roadmap",
            "repo_owner": "octo",
            "repo_name": "reef",
            "metadata": {"reviewers": ["ghillie-admin"]},
        },
    )


def _create_issue_event(repo_slug: str, occurred_at: dt.datetime) -> RawEventEnvelope:
    """Build an issue RawEventEnvelope for the scenario."""
    return RawEventEnvelope(
        source_system="github",
        source_event_id="issue-silver",
        event_type="github.issue",
        repo_external_id=repo_slug,
        occurred_at=occurred_at,
        payload={
            "id": 5,
            "number": 5,
            "title": "Document new governance hooks",
            "author_login": "compliance-team",
            "state": "closed",
            "created_at": "2024-07-04T18:00:00Z",
            "closed_at": "2024-07-05T09:00:00Z",
            "labels": ["documentation"],
            "repo_owner": "octo",
            "repo_name": "reef",
            "metadata": {"triage": "needs-release-note"},
        },
    )


def _create_doc_change_event(
    repo_slug: str, commit_sha: str, occurred_at: dt.datetime
) -> RawEventEnvelope:
    """Build a documentation change RawEventEnvelope for the scenario."""
    return RawEventEnvelope(
        source_system="github",
        source_event_id="doc-silver",
        event_type="github.doc_change",
        repo_external_id=repo_slug,
        occurred_at=occurred_at,
        payload={
            "commit_sha": commit_sha,
            "path": "docs/roadmap.md",
            "change_type": "modified",
            "is_roadmap": True,
            "is_adr": False,
            "repo_owner": "octo",
            "repo_name": "reef",
            "occurred_at": "2024-07-06T11:25:00Z",
            "metadata": {"summary": "Q3 milestones added"},
        },
    )


@when('I ingest GitHub entity events for "octo/reef"')
def ingest_entity_events(silver_context: SilverContext) -> None:
    """Insert commit, pull request, issue, and doc change raw events."""
    repo_slug = silver_context["repo_slug"]
    commit_sha = silver_context["commit_sha"]
    writer = silver_context["writer"]
    occurred_at = dt.datetime(2024, 7, 6, 11, 30, tzinfo=dt.UTC)

    async def _run() -> None:
        await writer.ingest(_create_commit_event(repo_slug, commit_sha, occurred_at))
        await writer.ingest(_create_pull_request_event(repo_slug, occurred_at))
        await writer.ingest(_create_issue_event(repo_slug, occurred_at))
        await writer.ingest(
            _create_doc_change_event(repo_slug, commit_sha, occurred_at)
        )

    _run_async(_run)


@when("I transform pending raw events for Silver entities")
def transform_pending_events(silver_context: SilverContext) -> None:
    """Run the Bronze→Silver transformation."""
    _run_async(silver_context["transformer"].process_pending)


@then('the Silver repositories table contains "octo/reef"')
def assert_repository_exists(silver_context: SilverContext) -> None:
    """Verify the repository record is present."""

    async def _assert() -> None:
        async with silver_context["session_factory"]() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == "octo",
                    Repository.github_name == "reef",
                )
            )
            assert repo is not None
            assert repo.default_branch == "main"

    _run_async(_assert)


@then('the Silver commits table includes commit "abc123" for "octo/reef"')
def assert_commit_exists(silver_context: SilverContext) -> None:
    """Verify the commit is linked to the repository."""

    async def _assert() -> None:
        async with silver_context["session_factory"]() as session:
            repo = await session.scalar(
                select(Repository).where(
                    Repository.github_owner == "octo",
                    Repository.github_name == "reef",
                )
            )
            assert repo is not None
            commit = await session.get(Commit, silver_context["commit_sha"])
            assert commit is not None
            assert commit.repo_id == repo.id
            assert commit.message == "docs: flesh out roadmap"

    _run_async(_assert)


@then('the Silver pull requests table includes number 17 for "octo/reef"')
def assert_pull_request_exists(silver_context: SilverContext) -> None:
    """Verify the pull request row exists and is linked."""

    async def _assert() -> None:
        async with silver_context["session_factory"]() as session:
            pr = await session.get(PullRequest, 17)
            assert pr is not None
            assert pr.repo_id is not None
            assert pr.state == "merged"
            assert pr.labels == ["feature", "roadmap"]

    _run_async(_assert)


@then('the Silver issues table includes number 5 for "octo/reef"')
def assert_issue_exists(silver_context: SilverContext) -> None:
    """Verify the issue row exists and is linked."""

    async def _assert() -> None:
        async with silver_context["session_factory"]() as session:
            issue = await session.get(Issue, 5)
            assert issue is not None
            assert issue.repo_id is not None
            assert issue.state == "closed"
            assert issue.labels == ["documentation"]

    _run_async(_assert)


@then(
    'the Silver documentation changes table includes "docs/roadmap.md" for '
    'commit "abc123"'
)
def assert_documentation_change_exists(silver_context: SilverContext) -> None:
    """Verify documentation change is anchored to the commit and repository."""

    async def _assert() -> None:
        async with silver_context["session_factory"]() as session:
            doc_change = await session.scalar(
                select(DocumentationChange).where(
                    DocumentationChange.commit_sha == silver_context["commit_sha"],
                    DocumentationChange.path == "docs/roadmap.md",
                )
            )
            assert doc_change is not None
            assert doc_change.is_roadmap is True
            assert doc_change.is_adr is False

    _run_async(_assert)
