"""Unit tests for the GitHub GraphQL client."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import secrets
import typing as typ

import httpx
import pytest

from ghillie.github import GitHubGraphQLClient, GitHubGraphQLConfig
from ghillie.github.errors import GitHubAPIError
from ghillie.registry.models import RepositoryInfo

_TOKEN = secrets.token_hex(8)
_HTTP_ERROR_STATUS = 500
_PR_DATABASE_ID = 17


def _repo() -> RepositoryInfo:
    return RepositoryInfo(
        id="repo-1",
        owner="octo",
        name="reef",
        default_branch="main",
        ingestion_enabled=True,
        documentation_paths=("docs/roadmap.md",),
        estate_id=None,
    )


def _make_client(
    payloads: list[tuple[int, dict[str, typ.Any]]],
) -> tuple[GitHubGraphQLClient, httpx.AsyncClient, list[dict[str, typ.Any]]]:
    calls: list[dict[str, typ.Any]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append(body)
        status, payload = payloads[len(calls) - 1]
        return httpx.Response(status_code=status, json=payload)

    transport = httpx.MockTransport(_handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = GitHubGraphQLClient(
        GitHubGraphQLConfig(
            token=_TOKEN,
            endpoint="https://example.test/graphql",
        ),
        http_client=http_client,
    )
    return client, http_client, calls


def _make_pr_graphql_response(
    pr_nodes: list[dict[str, typ.Any]],
    *,
    has_next_page: bool = False,
    end_cursor: str | None = None,
) -> tuple[int, dict[str, typ.Any]]:
    """Build a GraphQL response for pull requests query."""
    edges = [
        {
            "cursor": node["cursor"],
            "node": {key: value for key, value in node.items() if key != "cursor"},
        }
        for node in pr_nodes
    ]
    return (
        200,
        {
            "data": {
                "repository": {
                    "pullRequests": {
                        "pageInfo": {
                            "hasNextPage": has_next_page,
                            "endCursor": end_cursor,
                        },
                        "edges": edges,
                    }
                }
            }
        },
    )


@dataclasses.dataclass(frozen=True, slots=True)
class _PrNodeSpec:
    """Specification for creating a test pull request node."""

    cursor: str
    database_id: int
    number: int
    title: str
    updated_at: str
    state: str = "OPEN"
    is_draft: bool = False
    merged_at: str | None = None
    closed_at: str | None = None
    base_ref_name: str = "main"
    head_ref_name: str = "feature/example"
    author_login: str = "octo"
    labels: list[str] = dataclasses.field(default_factory=list)


def _make_pr_node(spec: _PrNodeSpec) -> dict[str, typ.Any]:
    """Create a test pull request node for GraphQL response mocks."""
    return {
        "cursor": spec.cursor,
        "databaseId": spec.database_id,
        "number": spec.number,
        "title": spec.title,
        "state": spec.state,
        "isDraft": spec.is_draft,
        "createdAt": spec.updated_at,
        "updatedAt": spec.updated_at,
        "mergedAt": spec.merged_at,
        "closedAt": spec.closed_at,
        "baseRefName": spec.base_ref_name,
        "headRefName": spec.head_ref_name,
        "author": {"login": spec.author_login},
        "labels": {"nodes": [{"name": label} for label in spec.labels]},
    }


@dataclasses.dataclass(frozen=True, slots=True)
class _IssueNodeSpec:
    """Specification for creating a test issue node."""

    database_id: int
    number: int
    title: str
    updated_at: str
    state: str = "OPEN"
    author_login: str = "octo"


def _make_issue_node(spec: _IssueNodeSpec) -> dict[str, typ.Any]:
    """Create a test issue node for GraphQL response mocks."""
    return {
        "databaseId": spec.database_id,
        "number": spec.number,
        "title": spec.title,
        "state": spec.state,
        "createdAt": spec.updated_at,
        "updatedAt": spec.updated_at,
        "closedAt": None,
        "author": {"login": spec.author_login},
        "labels": {"nodes": []},
    }


def _make_issues_page(
    issues: list[tuple[str, dict[str, typ.Any]]],
    *,
    has_next_page: bool,
    end_cursor: str,
) -> tuple[int, dict[str, typ.Any]]:
    """Create a test GraphQL issues response page."""
    edges = [{"cursor": cursor, "node": node} for cursor, node in issues]
    return (
        200,
        {
            "data": {
                "repository": {
                    "issues": {
                        "pageInfo": {
                            "hasNextPage": has_next_page,
                            "endCursor": end_cursor,
                        },
                        "edges": edges,
                    }
                }
            }
        },
    )


@dataclasses.dataclass(frozen=True, slots=True)
class _CommitNodeSpec:
    """Specification for creating a test commit node."""

    oid: str
    message: str
    authored_date: str
    committed_date: str
    author_name: str = "Octo"
    author_email: str = "o@example.com"


def _make_commit_node(spec: _CommitNodeSpec) -> dict[str, typ.Any]:
    """Create a test commit node for GraphQL response mocks."""
    return {
        "oid": spec.oid,
        "message": spec.message,
        "authoredDate": spec.authored_date,
        "committedDate": spec.committed_date,
        "author": {"name": spec.author_name, "email": spec.author_email},
    }


def _make_doc_changes_page(
    commits: list[tuple[str, dict[str, typ.Any]]],
    *,
    has_next_page: bool,
    end_cursor: str,
) -> tuple[int, dict[str, typ.Any]]:
    """Create a test GraphQL doc changes response page."""
    edges = [{"cursor": cursor, "node": node} for cursor, node in commits]
    return (
        200,
        {
            "data": {
                "repository": {
                    "ref": {
                        "target": {
                            "history": {
                                "pageInfo": {
                                    "hasNextPage": has_next_page,
                                    "endCursor": end_cursor,
                                },
                                "edges": edges,
                            }
                        }
                    }
                }
            }
        },
    )


@pytest.mark.asyncio
async def test_graphql_raises_on_http_error() -> None:
    """_graphql raises a GitHubAPIError for HTTP error status codes."""
    client, http_client, _ = _make_client([(_HTTP_ERROR_STATUS, {"data": {}})])
    try:
        with pytest.raises(GitHubAPIError) as exc:
            await client._graphql("query { viewer { login } }", {})
        assert exc.value.status_code == _HTTP_ERROR_STATUS
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_graphql_raises_on_graphql_errors_payload() -> None:
    """_graphql raises a GitHubAPIError when a GraphQL errors payload exists."""
    client, http_client, _ = _make_client([(200, {"errors": [{"message": "nope"}]})])
    try:
        with pytest.raises(GitHubAPIError):
            await client._graphql("query { viewer { login } }", {})
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_iter_pull_requests_paginates_and_applies_since_filter() -> None:
    """iter_pull_requests yields newer events and stops at the since watermark."""
    repo = _repo()
    since = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    updated_new = dt.datetime(2025, 1, 2, tzinfo=dt.UTC).isoformat()
    updated_old = dt.datetime(2025, 1, 1, tzinfo=dt.UTC).isoformat()

    pr_new = _make_pr_node(
        _PrNodeSpec(
            cursor="cursor-new",
            database_id=17,
            number=17,
            title="Add release checklist",
            updated_at=updated_new,
            head_ref_name="feature/release-checklist",
            labels=["docs"],
        )
    )
    pr_old = _make_pr_node(
        _PrNodeSpec(
            cursor="cursor-old",
            database_id=99,
            number=99,
            title="Older PR",
            updated_at=updated_old,
            head_ref_name="feature/old",
        )
    )
    page_1 = _make_pr_graphql_response(
        [pr_new, pr_old],
        has_next_page=True,
        end_cursor="cursor-next",
    )
    client, http_client, calls = _make_client([page_1])
    try:
        events = [event async for event in client.iter_pull_requests(repo, since=since)]
        assert len(events) == 1
        event = events[0]
        assert event.event_type == "github.pull_request"
        assert event.source_event_id == "17"
        assert event.cursor == "cursor-new"
        assert event.payload["id"] == _PR_DATABASE_ID
        assert event.payload["labels"] == ["docs"]
        assert event.payload["state"] == "open"
        assert event.payload["metadata"]["updated_at"] == updated_new
        assert len(calls) == 1
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_iter_issues_forwards_after_cursor_and_paginates() -> None:
    """iter_issues forwards `after` and paginates using endCursor."""
    repo = _repo()
    since = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    updated_1 = dt.datetime(2025, 1, 3, tzinfo=dt.UTC).isoformat()
    updated_2 = dt.datetime(2025, 1, 2, tzinfo=dt.UTC).isoformat()

    page_1 = _make_issues_page(
        [
            (
                "cursor-1",
                _make_issue_node(
                    _IssueNodeSpec(
                        101,
                        101,
                        "Fix flaky integration test",
                        updated_1,
                    )
                ),
            ),
        ],
        has_next_page=True,
        end_cursor="cursor-page-1",
    )
    page_2 = _make_issues_page(
        [
            (
                "cursor-2",
                _make_issue_node(
                    _IssueNodeSpec(
                        102,
                        102,
                        "Second page issue",
                        updated_2,
                    )
                ),
            ),
        ],
        has_next_page=False,
        end_cursor="cursor-page-2",
    )
    client, http_client, calls = _make_client([page_1, page_2])
    try:
        events = [
            event
            async for event in client.iter_issues(repo, since=since, after="resume")
        ]
        assert [event.source_event_id for event in events] == ["101", "102"]
        first = calls[0]
        assert first["variables"]["after"] == "resume"
        second = calls[1]
        assert second["variables"]["after"] == "cursor-page-1"
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_iter_pull_requests_coerces_merged_state() -> None:
    """iter_pull_requests reports merged PRs as state=merged."""
    repo = _repo()
    since = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    updated = dt.datetime(2025, 1, 2, tzinfo=dt.UTC).isoformat()

    pr_merged = _make_pr_node(
        _PrNodeSpec(
            cursor="cursor",
            database_id=55,
            number=55,
            title="Merge me",
            updated_at=updated,
            state="CLOSED",
            merged_at=updated,
            closed_at=updated,
            head_ref_name="feature/merge",
        )
    )
    page = _make_pr_graphql_response([pr_merged], has_next_page=False, end_cursor="c")
    client, http_client, _ = _make_client([page])
    try:
        events = [event async for event in client.iter_pull_requests(repo, since=since)]
        assert events[0].payload["state"] == "merged"
    finally:
        await http_client.aclose()


@pytest.mark.asyncio
async def test_iter_doc_changes_classifies_documentation_paths() -> None:
    """iter_doc_changes classifies roadmap and ADR paths in payload."""
    repo = _repo()
    since = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    committed = dt.datetime(2025, 1, 2, tzinfo=dt.UTC).isoformat()
    commit = _make_commit_node(
        _CommitNodeSpec(
            "abc123",
            "docs: refresh roadmap",
            committed,
            committed,
        )
    )
    page = _make_doc_changes_page(
        [("cursor-1", commit)],
        has_next_page=False,
        end_cursor="c",
    )
    client, http_client, _ = _make_client([page])
    try:
        events = [
            event
            async for event in client.iter_doc_changes(
                repo,
                since=since,
                documentation_paths=["docs/roadmap.md"],
            )
        ]
        assert len(events) == 1
        payload = events[0].payload
        assert payload["path"] == "docs/roadmap.md"
        assert payload["is_roadmap"] is True
        assert payload["is_adr"] is False
        assert payload["metadata"]["message"] == "docs: refresh roadmap"
    finally:
        await http_client.aclose()
