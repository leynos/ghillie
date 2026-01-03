"""Shared event envelope builders for evidence tests.

This module provides deterministic RawEventEnvelope constructors used across
unit and behavioural tests for evidence bundle generation.

Each event type has a corresponding spec dataclass (e.g., `PREventSpec`,
`CommitEventSpec`) that encapsulates the event parameters and provides a
`build()` method to create the raw envelope. For convenience, the
`commit_envelope` function provides a simpler interface for commit events.

Examples
--------
Create a pull request event using PREventSpec:

>>> from datetime import datetime, timezone
>>> from tests.helpers.event_builders import PREventSpec
>>>
>>> spec = PREventSpec(
...     repo_slug="owner/repo",
...     pr_id=1,
...     pr_number=42,
...     created_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
...     title="Add new feature",
...     labels=("enhancement",),
... )
>>> envelope = spec.build()
>>> envelope.event_type
'github.pull_request'

Create a commit event using CommitEventSpec:

>>> from tests.helpers.event_builders import CommitEventSpec
>>>
>>> spec = CommitEventSpec(
...     repo_slug="owner/repo",
...     commit_sha="abc123def456",
...     occurred_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
...     message="fix: resolve authentication bug",
... )
>>> envelope = spec.build()
>>> envelope.event_type
'github.commit'

Or use the convenience function for commits:

>>> from tests.helpers.event_builders import commit_envelope
>>>
>>> envelope = commit_envelope(
...     repo_slug="owner/repo",
...     commit_sha="abc123",
...     occurred_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
... )

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
    """Base specification for creating event envelopes with repo metadata.

    This dataclass provides the foundation for building test event envelopes
    with automatic repository metadata enrichment. Specialized specs (PREventSpec,
    IssueEventSpec, etc.) delegate to this class for envelope construction.

    Parameters
    ----------
    repo_slug : str
        Repository identifier in "owner/name" format.
    source_event_id : str
        Unique identifier for the source event.
    event_type : str
        GitHub event type (e.g., "github.pull_request", "github.commit").
    occurred_at : datetime
        Timestamp when the event occurred.
    payload : dict[str, Any]
        Event-specific payload data.

    Examples
    --------
    >>> from datetime import datetime, timezone
    >>> spec = BaseEventSpec(
    ...     repo_slug="owner/repo",
    ...     source_event_id="event-123",
    ...     event_type="github.commit",
    ...     occurred_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    ...     payload={"sha": "abc123"},
    ... )
    >>> envelope = spec.build()

    """

    repo_slug: str
    source_event_id: str
    event_type: str
    occurred_at: dt.datetime
    payload: dict[str, typ.Any]

    def build(self) -> RawEventEnvelope:
        """Build a RawEventEnvelope with common repo metadata enrichment.

        Returns
        -------
        RawEventEnvelope
            The constructed envelope with repo_owner and repo_name injected
            into the payload.

        """
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
    """Specification for creating a pull request test event.

    Parameters
    ----------
    repo_slug : str
        Repository identifier in "owner/name" format.
    pr_id : int
        Unique database identifier for the pull request.
    pr_number : int
        Pull request number within the repository.
    created_at : datetime
        Timestamp when the pull request was created.
    title : str, optional
        Pull request title (default: "Add feature").
    state : str, optional
        Pull request state, e.g., "open" or "closed" (default: "open").
    labels : tuple of str, optional
        Labels attached to the pull request (default: empty tuple).
    merged_at : datetime or None, optional
        Timestamp when the PR was merged, or None if not merged.

    Examples
    --------
    >>> from datetime import datetime, timezone
    >>> spec = PREventSpec(
    ...     repo_slug="owner/repo",
    ...     pr_id=1,
    ...     pr_number=42,
    ...     created_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    ... )
    >>> envelope = spec.build()

    """

    repo_slug: str
    pr_id: int
    pr_number: int
    created_at: dt.datetime
    title: str = "Add feature"
    state: str = "open"
    labels: tuple[str, ...] = ()
    merged_at: dt.datetime | None = None

    def build(self) -> RawEventEnvelope:
        """Build a RawEventEnvelope from this specification.

        Returns
        -------
        RawEventEnvelope
            A pull request event envelope with standard test defaults.

        """
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
    """Specification for creating an issue test event.

    Parameters
    ----------
    repo_slug : str
        Repository identifier in "owner/name" format.
    issue_id : int
        Unique database identifier for the issue.
    issue_number : int
        Issue number within the repository.
    created_at : datetime
        Timestamp when the issue was created.
    title : str, optional
        Issue title (default: "Bug report").
    state : str, optional
        Issue state, e.g., "open" or "closed" (default: "open").
    labels : tuple of str, optional
        Labels attached to the issue (default: empty tuple).

    Examples
    --------
    >>> from datetime import datetime, timezone
    >>> spec = IssueEventSpec(
    ...     repo_slug="owner/repo",
    ...     issue_id=1,
    ...     issue_number=10,
    ...     created_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    ... )
    >>> envelope = spec.build()

    """

    repo_slug: str
    issue_id: int
    issue_number: int
    created_at: dt.datetime
    title: str = "Bug report"
    state: str = "open"
    labels: tuple[str, ...] = ()

    def build(self) -> RawEventEnvelope:
        """Build a RawEventEnvelope from this specification.

        Returns
        -------
        RawEventEnvelope
            An issue event envelope with standard test defaults.

        """
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
    """Specification for creating a documentation change test event.

    Parameters
    ----------
    repo_slug : str
        Repository identifier in "owner/name" format.
    commit_sha : str
        SHA of the commit containing the documentation change.
    path : str
        File path of the changed documentation file.
    occurred_at : datetime
        Timestamp when the change occurred.
    is_roadmap : bool, optional
        Whether the file is a roadmap document (default: False).

    Examples
    --------
    >>> from datetime import datetime, timezone
    >>> spec = DocChangeEventSpec(
    ...     repo_slug="owner/repo",
    ...     commit_sha="abc123",
    ...     path="docs/README.md",
    ...     occurred_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    ... )
    >>> envelope = spec.build()

    """

    repo_slug: str
    commit_sha: str
    path: str
    occurred_at: dt.datetime
    is_roadmap: bool = False

    def build(self) -> RawEventEnvelope:
        """Build a RawEventEnvelope from this specification.

        Returns
        -------
        RawEventEnvelope
            A documentation change event envelope with standard test defaults.

        """
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


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class CommitEventSpec:
    """Specification for creating a commit test event.

    Parameters
    ----------
    repo_slug : str
        Repository identifier in "owner/name" format.
    commit_sha : str
        SHA of the commit.
    occurred_at : datetime
        Timestamp when the commit occurred.
    message : str, optional
        Commit message (default: "add feature").

    Examples
    --------
    >>> from datetime import datetime, timezone
    >>> spec = CommitEventSpec(
    ...     repo_slug="owner/repo",
    ...     commit_sha="abc123",
    ...     occurred_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    ... )
    >>> envelope = spec.build()

    """

    repo_slug: str
    commit_sha: str
    occurred_at: dt.datetime
    message: str = "add feature"

    def build(self) -> RawEventEnvelope:
        """Build a RawEventEnvelope from this specification.

        Returns
        -------
        RawEventEnvelope
            A commit event envelope with standard test defaults.

        """
        return BaseEventSpec(
            repo_slug=self.repo_slug,
            source_event_id=f"commit-{self.commit_sha}",
            event_type="github.commit",
            occurred_at=self.occurred_at,
            payload={
                "sha": self.commit_sha,
                "message": self.message,
                "author_email": "dev@example.com",
                "author_name": "Dev",
                "authored_at": self.occurred_at.isoformat(),
                "committed_at": self.occurred_at.isoformat(),
                "default_branch": "main",
            },
        ).build()


def commit_envelope(
    repo_slug: str,
    commit_sha: str,
    occurred_at: dt.datetime,
    message: str = "add feature",
) -> RawEventEnvelope:
    """Create a minimal commit raw event envelope.

    Parameters
    ----------
    repo_slug : str
        Repository identifier in "owner/name" format.
    commit_sha : str
        SHA of the commit.
    occurred_at : datetime
        Timestamp when the commit occurred.
    message : str, optional
        Commit message (default: "add feature").

    Returns
    -------
    RawEventEnvelope
        A commit event envelope with standard test defaults.

    Examples
    --------
    >>> from datetime import datetime, timezone
    >>> envelope = commit_envelope(
    ...     repo_slug="owner/repo",
    ...     commit_sha="abc123",
    ...     occurred_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    ... )

    """
    return CommitEventSpec(
        repo_slug=repo_slug,
        commit_sha=commit_sha,
        occurred_at=occurred_at,
        message=message,
    ).build()


__all__ = [
    "BaseEventSpec",
    "CommitEventSpec",
    "DocChangeEventSpec",
    "IssueEventSpec",
    "PREventSpec",
    "commit_envelope",
]
