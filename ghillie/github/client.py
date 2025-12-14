"""GitHub API client implementations used by ingestion workers."""

from __future__ import annotations

import dataclasses
import datetime as dt
import functools
import os
import typing as typ
from typing import TypeVar  # noqa: ICN003,F401

import httpx

from .errors import GitHubAPIError, GitHubConfigError, GitHubResponseShapeError
from .models import GitHubIngestedEvent

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from ghillie.registry.models import RepositoryInfo


class GitHubActivityClient(typ.Protocol):
    """Interface for fetching GitHub activity for ingestion."""

    def iter_commits(
        self, repo: RepositoryInfo, *, since: dt.datetime
    ) -> cabc.AsyncIterator[GitHubIngestedEvent]:
        """Yield commit events on the default branch since a timestamp."""
        ...

    def iter_pull_requests(
        self, repo: RepositoryInfo, *, since: dt.datetime
    ) -> cabc.AsyncIterator[GitHubIngestedEvent]:
        """Yield pull request snapshot events updated since a timestamp."""
        ...

    def iter_issues(
        self, repo: RepositoryInfo, *, since: dt.datetime
    ) -> cabc.AsyncIterator[GitHubIngestedEvent]:
        """Yield issue snapshot events updated since a timestamp."""
        ...

    def iter_doc_changes(
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        documentation_paths: typ.Sequence[str],
    ) -> cabc.AsyncIterator[GitHubIngestedEvent]:
        """Yield documentation change events for configured paths since a timestamp."""
        ...


@dataclasses.dataclass(frozen=True, slots=True)
class GitHubGraphQLConfig:
    """Configuration for the GitHub GraphQL API client."""

    token: str
    endpoint: str = "https://api.github.com/graphql"
    timeout_s: float = 20.0
    user_agent: str = "ghillie/0.1"

    @classmethod
    def from_env(cls) -> GitHubGraphQLConfig:
        """Build configuration using the `GHILLIE_GITHUB_TOKEN` env var."""
        token = os.environ.get("GHILLIE_GITHUB_TOKEN", "").strip()
        if not token:
            raise GitHubConfigError.missing_token()
        return cls(token=token)


_COMMITS_QUERY = """
query(
  $owner: String!
  $name: String!
  $qualifiedName: String!
  $since: GitTimestamp!
  $after: String
  $path: String
) {
  repository(owner: $owner, name: $name) {
    ref(qualifiedName: $qualifiedName) {
      target {
        ... on Commit {
          history(first: 100, since: $since, after: $after, path: $path) {
            pageInfo {
              hasNextPage
              endCursor
            }
            edges {
              cursor
              node {
                oid
                message
                authoredDate
                committedDate
                author {
                  name
                  email
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

_PULL_REQUESTS_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(
      first: 100
      after: $after
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        databaseId
        number
        title
        state
        isDraft
        createdAt
        updatedAt
        mergedAt
        closedAt
        baseRefName
        headRefName
        author { login }
        labels(first: 50) { nodes { name } }
      }
    }
  }
}
"""

_ISSUES_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(
      first: 100
      after: $after
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        databaseId
        number
        title
        state
        createdAt
        updatedAt
        closedAt
        author { login }
        labels(first: 50) { nodes { name } }
      }
    }
  }
}
"""

_HTTP_ERROR_STATUS_THRESHOLD = 400


def _ensure_tzaware(value: dt.datetime, *, field: str) -> dt.datetime:
    if value.tzinfo is None:
        msg = f"{field} must be timezone-aware"
        raise ValueError(msg)
    return value.astimezone(dt.UTC)


def _parse_github_datetime(value: str) -> dt.datetime:
    text = value.replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        msg = f"GitHub datetime missing timezone: {value}"
        raise ValueError(msg)
    return parsed.astimezone(dt.UTC)


def _label_names(labels: dict[str, typ.Any] | None) -> list[str]:
    if not labels:
        return []
    nodes = labels.get("nodes") or []
    if not isinstance(nodes, list):
        return []
    names: list[str] = []
    for node in nodes:
        if isinstance(node, dict):
            name = node.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def _maybe_login(author: dict[str, typ.Any] | None) -> str | None:
    if not author:
        return None
    login = author.get("login")
    return login if isinstance(login, str) else None


def _coerce_pr_state(state: str, merged_at: str | None) -> str:
    lowered = state.lower()
    if lowered == "closed" and merged_at:
        return "merged"
    return lowered


def _classify_documentation_path(path: str) -> tuple[bool, bool]:
    lowered = path.lower()
    is_roadmap = "roadmap" in lowered
    is_adr = (
        "/adr" in lowered
        or lowered.endswith("adr")
        or "architecture-decision" in lowered
    )
    return is_roadmap, is_adr


def _connection_edges(
    connection: dict[str, typ.Any],
    *,
    field: str,
) -> list[dict[str, typ.Any]]:
    edges = connection.get("edges")
    if not isinstance(edges, list):
        raise GitHubResponseShapeError.missing(f"{field}.edges")
    return [edge for edge in edges if isinstance(edge, dict)]


def _connection_nodes(
    connection: dict[str, typ.Any],
    *,
    field: str,
) -> list[dict[str, typ.Any]]:
    nodes = connection.get("nodes")
    if not isinstance(nodes, list):
        raise GitHubResponseShapeError.missing(f"{field}.nodes")
    return [node for node in nodes if isinstance(node, dict)]


def _commit_event_from_node(
    repo: RepositoryInfo,
    node: dict[str, typ.Any],
    since: dt.datetime,
) -> GitHubIngestedEvent | None:
    oid = node.get("oid")
    committed_date = node.get("committedDate")
    if not isinstance(oid, str) or not isinstance(committed_date, str):
        return None

    occurred_at = _parse_github_datetime(committed_date)
    if occurred_at <= since:
        return None

    raw_author = node.get("author")
    author = raw_author if isinstance(raw_author, dict) else None
    payload: dict[str, typ.Any] = {
        "sha": oid,
        "message": node.get("message"),
        "author_email": author.get("email") if author else None,
        "author_name": author.get("name") if author else None,
        "authored_at": node.get("authoredDate"),
        "committed_at": committed_date,
        "repo_owner": repo.owner,
        "repo_name": repo.name,
        "default_branch": repo.default_branch,
        "metadata": {"branch": repo.default_branch},
    }
    return GitHubIngestedEvent(
        event_type="github.commit",
        source_event_id=oid,
        occurred_at=occurred_at,
        payload=payload,
    )


def _iter_commit_events(
    repo: RepositoryInfo,
    edges: list[dict[str, typ.Any]],
    since: dt.datetime,
) -> typ.Iterator[GitHubIngestedEvent]:
    for edge in edges:
        node = edge.get("node")
        if not isinstance(node, dict):
            continue
        event = _commit_event_from_node(repo, node, since)
        if event is not None:
            yield event


@dataclasses.dataclass(frozen=True, slots=True)
class _DocChangeSpec:
    """Computed configuration for documentation change ingestion."""

    path: str
    is_roadmap: bool
    is_adr: bool


def _doc_change_event_from_node(
    repo: RepositoryInfo,
    node: dict[str, typ.Any],
    *,
    since: dt.datetime,
    spec: _DocChangeSpec,
) -> GitHubIngestedEvent | None:
    oid = node.get("oid")
    committed_date = node.get("committedDate")
    if not isinstance(oid, str) or not isinstance(committed_date, str):
        return None

    occurred_at = _parse_github_datetime(committed_date)
    if occurred_at <= since:
        return None

    payload: dict[str, typ.Any] = {
        "commit_sha": oid,
        "path": spec.path,
        "change_type": "modified",
        "is_roadmap": spec.is_roadmap,
        "is_adr": spec.is_adr,
        "repo_owner": repo.owner,
        "repo_name": repo.name,
        "occurred_at": committed_date,
        "metadata": {"message": node.get("message")},
    }
    return GitHubIngestedEvent(
        event_type="github.doc_change",
        source_event_id=f"{oid}:{spec.path}",
        occurred_at=occurred_at,
        payload=payload,
    )


def _iter_doc_change_events(
    repo: RepositoryInfo,
    edges: list[dict[str, typ.Any]],
    *,
    since: dt.datetime,
    spec: _DocChangeSpec,
) -> typ.Iterator[GitHubIngestedEvent]:
    for edge in edges:
        node = edge.get("node")
        if not isinstance(node, dict):
            continue
        event = _doc_change_event_from_node(
            repo,
            node,
            since=since,
            spec=spec,
        )
        if event is not None:
            yield event


class _PayloadBuilder[PayloadT: dict[str, typ.Any]](typ.Protocol):
    """Build an event payload dict from validated node fields."""

    def __call__(self, *, database_id: int, updated_at_raw: str) -> PayloadT:
        """Return the event payload for the given node identifiers."""
        ...


def _generic_event_from_node[PayloadT: dict[str, typ.Any]](
    event_type: str,
    node: dict[str, typ.Any],
    *,
    since: dt.datetime,
    payload_builder: _PayloadBuilder[PayloadT],
) -> tuple[GitHubIngestedEvent | None, bool]:
    """Create a GitHubIngestedEvent from a GraphQL node, or decide to stop.

    This helper centralises the shared parsing of `updatedAt` and `databaseId`
    fields for GitHub entities ordered by `UPDATED_AT`. It returns `(event,
    should_stop)`, where `should_stop=True` indicates the caller should stop
    paginating because results are older than or equal to the `since` watermark.
    """
    updated_at_raw = node.get("updatedAt")
    database_id = node.get("databaseId")
    if not isinstance(updated_at_raw, str) or not isinstance(database_id, int):
        return (None, False)

    updated_at = _parse_github_datetime(updated_at_raw)
    if updated_at <= since:
        return (None, True)

    payload = payload_builder(database_id=database_id, updated_at_raw=updated_at_raw)
    return (
        GitHubIngestedEvent(
            event_type=event_type,
            source_event_id=str(database_id),
            occurred_at=updated_at,
            payload=payload,
        ),
        False,
    )


def _build_pr_payload(
    repo: RepositoryInfo,
    node: dict[str, typ.Any],
    *,
    database_id: int,
    updated_at_raw: str,
) -> dict[str, typ.Any]:
    """Build a pull request payload dict from a GraphQL node."""
    merged_at = node.get("mergedAt")
    return {
        "id": database_id,
        "number": node.get("number"),
        "title": node.get("title"),
        "author_login": _maybe_login(node.get("author")),
        "state": _coerce_pr_state(str(node.get("state", "")), merged_at),
        "created_at": node.get("createdAt"),
        "merged_at": merged_at,
        "closed_at": node.get("closedAt"),
        "labels": _label_names(node.get("labels")),
        "is_draft": bool(node.get("isDraft", False)),
        "base_branch": node.get("baseRefName"),
        "head_branch": node.get("headRefName"),
        "repo_owner": repo.owner,
        "repo_name": repo.name,
        "metadata": {"updated_at": updated_at_raw},
    }


def _build_issue_payload(
    repo: RepositoryInfo,
    node: dict[str, typ.Any],
    *,
    database_id: int,
    updated_at_raw: str,
) -> dict[str, typ.Any]:
    """Build an issue payload dict from a GraphQL node."""
    return {
        "id": database_id,
        "number": node.get("number"),
        "title": node.get("title"),
        "author_login": _maybe_login(node.get("author")),
        "state": str(node.get("state", "")).lower(),
        "created_at": node.get("createdAt"),
        "closed_at": node.get("closedAt"),
        "labels": _label_names(node.get("labels")),
        "repo_owner": repo.owner,
        "repo_name": repo.name,
        "metadata": {"updated_at": updated_at_raw},
    }


class _NodeTransformer(typ.Protocol):
    """Transform a node into an optional event and stop signal."""

    def __call__(
        self, repo: RepositoryInfo, node: dict[str, typ.Any], *, since: dt.datetime
    ) -> tuple[GitHubIngestedEvent | None, bool]:
        """Return (event, should_stop)."""
        ...


def _generic_events_from_nodes(
    repo: RepositoryInfo,
    nodes: list[dict[str, typ.Any]],
    *,
    since: dt.datetime,
    node_transformer: _NodeTransformer,
) -> tuple[list[GitHubIngestedEvent], bool]:
    """Apply a node transformer across nodes, stopping when requested."""
    events: list[GitHubIngestedEvent] = []
    should_stop = False
    for node in nodes:
        event, stop = node_transformer(repo, node, since=since)
        if event is not None:
            events.append(event)
        if stop:
            should_stop = True
            break
    return events, should_stop


def _pull_request_event_from_node(
    repo: RepositoryInfo,
    node: dict[str, typ.Any],
    *,
    since: dt.datetime,
) -> tuple[GitHubIngestedEvent | None, bool]:
    return _generic_event_from_node(
        "github.pull_request",
        node,
        since=since,
        payload_builder=functools.partial(_build_pr_payload, repo, node),
    )


def _pull_request_events_from_nodes(
    repo: RepositoryInfo,
    nodes: list[dict[str, typ.Any]],
    *,
    since: dt.datetime,
) -> tuple[list[GitHubIngestedEvent], bool]:
    return _generic_events_from_nodes(
        repo,
        nodes,
        since=since,
        node_transformer=_pull_request_event_from_node,
    )


def _issue_event_from_node(
    repo: RepositoryInfo,
    node: dict[str, typ.Any],
    *,
    since: dt.datetime,
) -> tuple[GitHubIngestedEvent | None, bool]:
    return _generic_event_from_node(
        "github.issue",
        node,
        since=since,
        payload_builder=functools.partial(_build_issue_payload, repo, node),
    )


def _issue_events_from_nodes(
    repo: RepositoryInfo,
    nodes: list[dict[str, typ.Any]],
    *,
    since: dt.datetime,
) -> tuple[list[GitHubIngestedEvent], bool]:
    return _generic_events_from_nodes(
        repo,
        nodes,
        since=since,
        node_transformer=_issue_event_from_node,
    )


class _EventsExtractor(typ.Protocol):
    """Extract events (and stop signal) from a list of GraphQL nodes."""

    def __call__(
        self,
        repo: RepositoryInfo,
        nodes: list[dict[str, typ.Any]],
        *,
        since: dt.datetime,
    ) -> tuple[list[GitHubIngestedEvent], bool]:
        """Return (events, should_stop)."""
        ...


@dataclasses.dataclass(frozen=True, slots=True)
class _PaginatedEntityConfig:
    """Configuration for a paginated GraphQL entity type."""

    query: str
    connection_path: list[str]
    entity_name: str
    events_extractor: _EventsExtractor


_PR_CONFIG = _PaginatedEntityConfig(
    query=_PULL_REQUESTS_QUERY,
    connection_path=["repository", "pullRequests"],
    entity_name="pull request",
    events_extractor=_pull_request_events_from_nodes,
)
_ISSUES_CONFIG = _PaginatedEntityConfig(
    query=_ISSUES_QUERY,
    connection_path=["repository", "issues"],
    entity_name="issue",
    events_extractor=_issue_events_from_nodes,
)


class GitHubGraphQLClient:
    """GitHub GraphQL implementation of :class:`GitHubActivityClient`."""

    def __init__(
        self,
        config: GitHubGraphQLConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialise the client with the provided API configuration."""
        if not config.token.strip():
            raise GitHubConfigError.empty_token()

        self._config = config
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=config.timeout_s,
            headers={
                "Authorization": f"Bearer {config.token}",
                "User-Agent": config.user_agent,
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        """Close any owned HTTP resources."""
        if self._owns_client:
            await self._client.aclose()

    async def iter_commits(
        self, repo: RepositoryInfo, *, since: dt.datetime
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield commit snapshot events on the default branch."""
        since_utc = _ensure_tzaware(since, field="since")
        qualified_name = f"refs/heads/{repo.default_branch}"
        after: str | None = None

        while True:
            data = await self._graphql(
                _COMMITS_QUERY,
                {
                    "owner": repo.owner,
                    "name": repo.name,
                    "qualifiedName": qualified_name,
                    "since": since_utc.isoformat(),
                    "after": after,
                    "path": None,
                },
            )
            history = _extract_commit_history(data)
            edges = _connection_edges(history, field="commit history")
            for event in _iter_commit_events(repo, edges, since_utc):
                yield event

            page_info = history.get("pageInfo")
            if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
                return
            after = page_info.get("endCursor")
            if not isinstance(after, str):
                return

    async def _iter_paginated_entities(
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        config: _PaginatedEntityConfig,
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield entity snapshot events from a paginated GraphQL connection.

        This helper centralises the common pagination loop for connections
        ordered by `UPDATED_AT`, such as pull requests and issues. The
        `events_extractor` is responsible for converting nodes into
        GitHubIngestedEvent instances and signalling when iteration should stop
        because the nodes are older than the `since` watermark.
        """
        after: str | None = None
        while True:
            data = await self._graphql(
                config.query,
                {"owner": repo.owner, "name": repo.name, "after": after},
            )
            connection = _extract_connection(data, config.connection_path)
            nodes = _connection_nodes(connection, field=config.entity_name)
            events, should_stop = config.events_extractor(repo, nodes, since=since)
            for event in events:
                yield event
            if should_stop:
                return

            page_info = connection.get("pageInfo")
            if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
                return
            after = page_info.get("endCursor")
            if not isinstance(after, str):
                return

    async def iter_pull_requests(
        self, repo: RepositoryInfo, *, since: dt.datetime
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield pull request snapshot events updated since a timestamp."""
        since_utc = _ensure_tzaware(since, field="since")
        async for event in self._iter_paginated_entities(
            repo,
            since=since_utc,
            config=_PR_CONFIG,
        ):
            yield event

    async def iter_issues(
        self, repo: RepositoryInfo, *, since: dt.datetime
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield issue snapshot events updated since a timestamp."""
        since_utc = _ensure_tzaware(since, field="since")
        async for event in self._iter_paginated_entities(
            repo,
            since=since_utc,
            config=_ISSUES_CONFIG,
        ):
            yield event

    async def iter_doc_changes(
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        documentation_paths: typ.Sequence[str],
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield documentation change events for documentation path commits."""
        since_utc = _ensure_tzaware(since, field="since")
        qualified_name = f"refs/heads/{repo.default_branch}"

        for path in documentation_paths:
            after: str | None = None
            is_roadmap, is_adr = _classify_documentation_path(path)
            spec = _DocChangeSpec(path=path, is_roadmap=is_roadmap, is_adr=is_adr)
            while True:
                data = await self._graphql(
                    _COMMITS_QUERY,
                    {
                        "owner": repo.owner,
                        "name": repo.name,
                        "qualifiedName": qualified_name,
                        "since": since_utc.isoformat(),
                        "after": after,
                        "path": path,
                    },
                )
                history = _extract_commit_history(data)
                edges = _connection_edges(history, field="doc change commit history")
                for event in _iter_doc_change_events(
                    repo,
                    edges,
                    since=since_utc,
                    spec=spec,
                ):
                    yield event

                page_info = history.get("pageInfo")
                if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
                    break
                after = page_info.get("endCursor")
                if not isinstance(after, str):
                    break

    async def _graphql(
        self, query: str, variables: dict[str, typ.Any]
    ) -> dict[str, typ.Any]:
        response = await self._client.post(
            self._config.endpoint,
            json={"query": query, "variables": variables},
        )
        if response.status_code >= _HTTP_ERROR_STATUS_THRESHOLD:
            raise GitHubAPIError.http_error(response.status_code)
        payload = typ.cast("dict[str, typ.Any]", response.json())
        errors = payload.get("errors")
        if errors:
            raise GitHubAPIError.graphql_errors(errors)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise GitHubResponseShapeError.missing("data")
        return typ.cast("dict[str, typ.Any]", data)


def _extract_connection(
    data: dict[str, typ.Any], path: list[str]
) -> dict[str, typ.Any]:
    node: typ.Any = data
    for key in path:
        if not isinstance(node, dict):
            raise GitHubResponseShapeError.missing(".".join(path))
        node = node.get(key)
    if not isinstance(node, dict):
        raise GitHubResponseShapeError.missing(".".join(path))
    return typ.cast("dict[str, typ.Any]", node)


def _extract_commit_history(data: dict[str, typ.Any]) -> dict[str, typ.Any]:
    """Extract commit history from GraphQL response data."""
    return _extract_connection(data, ["repository", "ref", "target", "history"])
