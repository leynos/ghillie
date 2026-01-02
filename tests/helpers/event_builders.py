"""Shared event envelope builders for evidence tests.

This module provides deterministic RawEventEnvelope constructors used across
unit and behavioural tests for evidence bundle generation.
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt

from ghillie.bronze import RawEventEnvelope
from ghillie.common.slug import parse_repo_slug


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class BaseEventSpec:
    """Base specification for creating event envelopes with repo metadata."""

    repo_slug: str
    source_event_id: str
    event_type: str
    occurred_at: dt.datetime
    payload: dict[str, typ.Any]

    def build(self) -> RawEventEnvelope:
        """Build a RawEventEnvelope with common repo metadata enrichment."""
        owner, name = parse_repo_slug(self.repo_slug)
        enriched_payload = dict(self.payload)
        enriched_payload["repo_owner"] = owner
        enriched_payload["repo_name"] = name
        if "metadata" not in enriched_payload:
            enriched_payload["metadata"] = {}
        return RawEventEnvelope(
            source_system="github",
            source_event_id=self.source_event_id,
            event_type=self.event_type,
            repo_external_id=self.repo_slug,
            occurred_at=self.occurred_at,
            payload=enriched_payload,
        )


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class PREventSpec:
    """Specification for creating a pull request test event."""

    repo_slug: str
    pr_id: int
    pr_number: int
    created_at: dt.datetime
    title: str = "Add feature"
    state: str = "open"
    labels: tuple[str, ...] = ()
    merged_at: dt.datetime | None = None

    def build(self) -> RawEventEnvelope:
        """Build a RawEventEnvelope from this specification."""
        return BaseEventSpec(
            repo_slug=self.repo_slug,
            source_event_id=f"pr-{self.pr_id}",
            event_type="github.pull_request",
            occurred_at=self.created_at,
            payload={
                "id": self.pr_id,
                "number": self.pr_number,
                "title": self.title,
                "state": self.state,
                "base_branch": "main",
                "head_branch": "feature",
                "created_at": self.created_at.isoformat(),
                "author_login": "dev",
                "merged_at": self.merged_at.isoformat() if self.merged_at else None,
                "closed_at": None,
                "labels": list(self.labels),
                "is_draft": False,
            },
        ).build()


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class IssueEventSpec:
    """Specification for creating an issue test event."""

    repo_slug: str
    issue_id: int
    issue_number: int
    created_at: dt.datetime
    title: str = "Bug report"
    state: str = "open"
    labels: tuple[str, ...] = ()

    def build(self) -> RawEventEnvelope:
        """Build a RawEventEnvelope from this specification."""
        return BaseEventSpec(
            repo_slug=self.repo_slug,
            source_event_id=f"issue-{self.issue_id}",
            event_type="github.issue",
            occurred_at=self.created_at,
            payload={
                "id": self.issue_id,
                "number": self.issue_number,
                "title": self.title,
                "state": self.state,
                "created_at": self.created_at.isoformat(),
                "author_login": "user",
                "closed_at": None,
                "labels": list(self.labels),
            },
        ).build()


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class DocChangeEventSpec:
    """Specification for creating a documentation change test event."""

    repo_slug: str
    commit_sha: str
    path: str
    occurred_at: dt.datetime
    is_roadmap: bool = False

    def build(self) -> RawEventEnvelope:
        """Build a RawEventEnvelope from this specification."""
        return BaseEventSpec(
            repo_slug=self.repo_slug,
            source_event_id=f"doc-{self.commit_sha}-{self.path}",
            event_type="github.doc_change",
            occurred_at=self.occurred_at,
            payload={
                "commit_sha": self.commit_sha,
                "path": self.path,
                "change_type": "modified",
                "occurred_at": self.occurred_at.isoformat(),
                "is_roadmap": self.is_roadmap,
                "is_adr": False,
            },
        ).build()


def commit_envelope(
    repo_slug: str,
    commit_sha: str,
    occurred_at: dt.datetime,
    message: str = "add feature",
) -> RawEventEnvelope:
    """Create a minimal commit raw event envelope."""
    owner, name = parse_repo_slug(repo_slug)
    return RawEventEnvelope(
        source_system="github",
        source_event_id=f"commit-{commit_sha}",
        event_type="github.commit",
        repo_external_id=repo_slug,
        occurred_at=occurred_at,
        payload={
            "sha": commit_sha,
            "message": message,
            "author_email": "dev@example.com",
            "author_name": "Dev",
            "authored_at": occurred_at.isoformat(),
            "committed_at": occurred_at.isoformat(),
            "repo_owner": owner,
            "repo_name": name,
            "default_branch": "main",
            "metadata": {},
        },
    )


__all__ = [
    "BaseEventSpec",
    "DocChangeEventSpec",
    "IssueEventSpec",
    "PREventSpec",
    "commit_envelope",
]
