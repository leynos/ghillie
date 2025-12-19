"""Shared GitHub event builders for tests.

This module provides deterministic GitHubIngestedEvent constructors used across
unit and behavioural tests.
"""

from __future__ import annotations

import dataclasses
import typing as typ

from ghillie.github.models import GitHubIngestedEvent

if typ.TYPE_CHECKING:
    import datetime as dt

    from ghillie.registry.models import RepositoryInfo


@dataclasses.dataclass(frozen=True, slots=True)
class _NumberedItemSpec:
    """Specification for creating a test numbered item event (PR or issue)."""

    event_type: str
    item_id: int
    title: str
    extra_fields: dict[str, typ.Any] | None = None


def _create_commit_event(
    owner: str, name: str, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test commit event."""
    return GitHubIngestedEvent(
        event_type="github.commit",
        source_event_id="abc123",
        occurred_at=occurred_at,
        payload={
            "sha": "abc123",
            "repo_owner": owner,
            "repo_name": name,
            "default_branch": "main",
            "committed_at": occurred_at.isoformat(),
        },
    )


def _create_pr_event(
    owner: str, name: str, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test pull request event."""
    spec = _NumberedItemSpec(
        event_type="github.pull_request",
        item_id=17,
        title="Add release checklist",
        extra_fields={
            "base_branch": "main",
            "head_branch": "feature/release-checklist",
        },
    )
    payload: dict[str, typ.Any] = {
        "id": spec.item_id,
        "number": spec.item_id,
        "title": spec.title,
        "state": "open",
        "repo_owner": owner,
        "repo_name": name,
        "created_at": occurred_at.isoformat(),
    }
    if spec.extra_fields is not None:
        payload.update(spec.extra_fields)
    return GitHubIngestedEvent(
        event_type=spec.event_type,
        source_event_id=str(spec.item_id),
        occurred_at=occurred_at,
        payload=payload,
    )


def _create_issue_event(
    owner: str, name: str, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test issue event."""
    spec = _NumberedItemSpec(
        event_type="github.issue",
        item_id=101,
        title="Fix flaky integration test",
        extra_fields=None,
    )
    payload: dict[str, typ.Any] = {
        "id": spec.item_id,
        "number": spec.item_id,
        "title": spec.title,
        "state": "open",
        "repo_owner": owner,
        "repo_name": name,
        "created_at": occurred_at.isoformat(),
    }
    return GitHubIngestedEvent(
        event_type=spec.event_type,
        source_event_id=str(spec.item_id),
        occurred_at=occurred_at,
        payload=payload,
    )


def _create_doc_change_event(
    owner: str, name: str, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test documentation-change event."""
    return GitHubIngestedEvent(
        event_type="github.doc_change",
        source_event_id="abc123:docs/roadmap.md",
        occurred_at=occurred_at,
        payload={
            "commit_sha": "abc123",
            "path": "docs/roadmap.md",
            "change_type": "modified",
            "repo_owner": owner,
            "repo_name": name,
            "occurred_at": occurred_at.isoformat(),
            "is_roadmap": True,
            "is_adr": False,
        },
    )


def make_commit_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test commit event for the given repository."""
    event = _create_commit_event(repo.owner, repo.name, occurred_at)
    event.payload["default_branch"] = repo.default_branch
    return event


def make_pr_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test pull request event for the given repository."""
    return _create_pr_event(repo.owner, repo.name, occurred_at)


def make_issue_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test issue event for the given repository."""
    return _create_issue_event(repo.owner, repo.name, occurred_at)


def make_doc_change_event(
    repo: RepositoryInfo, occurred_at: dt.datetime
) -> GitHubIngestedEvent:
    """Create a test documentation-change event for the given repository."""
    return _create_doc_change_event(repo.owner, repo.name, occurred_at)
