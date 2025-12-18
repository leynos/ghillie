"""Test helpers for GitHub ingestion worker tests."""

from __future__ import annotations

import dataclasses
import datetime as dt  # noqa: TC003
import typing as typ

from ghillie.github.models import GitHubIngestedEvent
from ghillie.registry.models import RepositoryInfo


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


def make_repo_info() -> RepositoryInfo:
    """Build a RepositoryInfo for ingestion tests."""
    return RepositoryInfo(
        id="repo-1",
        owner="octo",
        name="reef",
        default_branch="main",
        ingestion_enabled=True,
        documentation_paths=("docs/roadmap.md",),
        estate_id=None,
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


def make_commit_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test commit event for the ingestion worker."""
    return make_event(
        occurred_at=occurred_at,
        spec=EventSpec(
            event_type="github.commit",
            source_event_id="abc123",
            payload={
                "sha": "abc123",
                "repo_owner": repo.owner,
                "repo_name": repo.name,
                "default_branch": repo.default_branch,
                "committed_at": occurred_at.isoformat(),
            },
        ),
    )


@dataclasses.dataclass(frozen=True, slots=True)
class NumberedItemSpec:
    """Specification for creating a test numbered item event (PR or issue)."""

    event_type: str
    item_id: int
    title: str
    extra_fields: dict[str, object] | None = None


def make_numbered_item_event(
    repo: RepositoryInfo,
    occurred_at: dt.datetime,
    spec: NumberedItemSpec,
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
    return make_event(
        occurred_at=occurred_at,
        spec=EventSpec(
            event_type=spec.event_type,
            source_event_id=str(spec.item_id),
            payload=payload,
        ),
    )


def make_pr_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test pull request event for the ingestion worker."""
    spec = NumberedItemSpec(
        event_type="github.pull_request",
        item_id=17,
        title="Add release checklist",
        extra_fields={
            "base_branch": "main",
            "head_branch": "feature/release-checklist",
        },
    )
    return make_numbered_item_event(repo, occurred_at, spec)


def make_issue_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test issue event for the ingestion worker."""
    spec = NumberedItemSpec(
        event_type="github.issue",
        item_id=101,
        title="Fix flaky integration test",
        extra_fields=None,
    )
    return make_numbered_item_event(repo, occurred_at, spec)


def make_doc_change_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test documentation-change event for the ingestion worker."""
    return make_event(
        occurred_at=occurred_at,
        spec=EventSpec(
            event_type="github.doc_change",
            source_event_id="abc123:docs/roadmap.md",
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
        ),
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
