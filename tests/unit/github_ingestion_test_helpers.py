"""Test helpers for GitHub ingestion worker tests."""

from __future__ import annotations

import dataclasses
import typing as typ

from ghillie.github.models import GitHubIngestedEvent
from ghillie.registry.models import RepositoryInfo
from tests.helpers.github_events import (
    make_commit_event,
    make_doc_change_event,
    make_issue_event,
    make_pr_event,
)

if typ.TYPE_CHECKING:
    import datetime as dt

__all__ = [
    "EventSpec",
    "FailingGitHubClient",
    "FakeGitHubClient",
    "make_commit_event",
    "make_commit_events_with_cursors",
    "make_disabled_repo_info",
    "make_doc_change_event",
    "make_event",
    "make_issue_event",
    "make_pr_event",
    "make_repo_info",
]


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

    def _find_start_index(
        self, events: list[GitHubIngestedEvent], after: str | None
    ) -> int:
        """Find the starting index after a given cursor, or 0 if no cursor."""
        if after is None:
            return 0

        for idx, event in enumerate(events):
            if event.cursor == after:
                return idx + 1

        return 0

    async def iter_commits(
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield commit events newer than `since`."""
        del repo
        start = self._find_start_index(self._commits, after)
        for event in self._commits[start:]:
            if event.occurred_at > since:
                yield event

    async def iter_pull_requests(
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield pull request events newer than `since`."""
        del repo
        start = self._find_start_index(self._pull_requests, after)
        for event in self._pull_requests[start:]:
            if event.occurred_at > since:
                yield event

    async def iter_issues(
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield issue events newer than `since`."""
        del repo
        start = self._find_start_index(self._issues, after)
        for event in self._issues[start:]:
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
        del repo, documentation_paths
        start = self._find_start_index(self._doc_changes, after)
        for event in self._doc_changes[start:]:
            if event.occurred_at > since:
                yield event


class FailingGitHubClient:
    """GitHubActivityClient implementation that raises errors for testing."""

    def __init__(self, error: BaseException) -> None:
        """Store the error to raise on any method call."""
        self._error = error

    def iter_commits(
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Raise the configured error."""
        del repo, since, after
        return _FailingAsyncIterator(self._error)

    def iter_pull_requests(
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Raise the configured error."""
        del repo, since, after
        return _FailingAsyncIterator(self._error)

    def iter_issues(
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Raise the configured error."""
        del repo, since, after
        return _FailingAsyncIterator(self._error)

    def iter_doc_changes(
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        documentation_paths: typ.Sequence[str],
        after: str | None = None,
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Raise the configured error."""
        del repo, since, documentation_paths, after
        return _FailingAsyncIterator(self._error)


class _FailingAsyncIterator:
    """Async iterator that raises a configured exception on iteration."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    def __aiter__(self) -> _FailingAsyncIterator:
        return self

    async def __anext__(self) -> GitHubIngestedEvent:
        raise self._error


def make_repo_info(*, estate_id: str | None = None) -> RepositoryInfo:
    """Build a RepositoryInfo for ingestion tests."""
    return RepositoryInfo(
        id="repo-1",
        owner="octo",
        name="reef",
        default_branch="main",
        ingestion_enabled=True,
        documentation_paths=("docs/roadmap.md",),
        estate_id=estate_id,
    )


def make_disabled_repo_info() -> RepositoryInfo:
    """Build a disabled RepositoryInfo for ingestion tests."""
    return dataclasses.replace(make_repo_info(), ingestion_enabled=False)


@dataclasses.dataclass(frozen=True, slots=True)
class EventSpec:
    """Specification for creating a test GitHubIngestedEvent."""

    event_type: str
    source_event_id: str
    payload: dict[str, typ.Any]
    cursor: str | None = None


def make_event(
    occurred_at: dt.datetime,
    spec: EventSpec,
) -> GitHubIngestedEvent:
    """Build a GitHubIngestedEvent for tests."""
    return GitHubIngestedEvent(
        event_type=spec.event_type,
        source_event_id=spec.source_event_id,
        occurred_at=occurred_at,
        payload=spec.payload,
        cursor=spec.cursor,
    )


def make_commit_events_with_cursors(
    repo: RepositoryInfo,
    specs: list[tuple[str, dt.datetime, str]],
) -> list[GitHubIngestedEvent]:
    """Create test commit events with cursor support.

    Args:
        repo: Repository information
        specs: List of (sha, occurred_at, cursor) tuples

    """
    return [
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
                },
                cursor=cursor,
            ),
        )
        for sha, occurred_at, cursor in specs
    ]
