"""GitHub API client implementations used by ingestion workers."""

from __future__ import annotations

import collections.abc as cabc
import dataclasses
import datetime as dt
import os
import typing as typ
from pathlib import PurePosixPath, PureWindowsPath

import httpx

from ghillie.registry.models import RepositoryInfo

from .errors import GitHubAPIError, GitHubConfigError, GitHubResponseShapeError
from .models import GitHubIngestedEvent


class GitHubActivityClient(typ.Protocol):
    """Interface for fetching GitHub activity for ingestion."""

    def iter_commits(
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> cabc.AsyncIterator[GitHubIngestedEvent]:
        """Yield commit events on the default branch since a timestamp."""
        ...

    def iter_pull_requests(
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> cabc.AsyncIterator[GitHubIngestedEvent]:
        """Yield pull request snapshot events updated since a timestamp."""
        ...

    def iter_issues(
        self, repo: RepositoryInfo, *, since: dt.datetime, after: str | None = None
    ) -> cabc.AsyncIterator[GitHubIngestedEvent]:
        """Yield issue snapshot events updated since a timestamp."""
        ...

    def iter_doc_changes(
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        documentation_paths: typ.Sequence[str],
        after: str | None = None,
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
      edges {
        cursor
        node {
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
      edges {
        cursor
        node {
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
    normalised = PureWindowsPath(lowered).as_posix()
    path_parts = [
        part for part in PurePosixPath(normalised).parts if part not in {"", "/"}
    ]
    directory_parts = (
        path_parts[:-1]
        if path_parts and PurePosixPath(path_parts[-1]).suffix
        else path_parts
    )
    is_adr = "adr" in path_parts or any(
        "architecture-decision" in segment for segment in directory_parts
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
    *,
    cursor: str | None = None,
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
        cursor=cursor,
    )


def _iter_commit_events(
    repo: RepositoryInfo,
    edges: list[dict[str, typ.Any]],
    since: dt.datetime,
) -> typ.Iterator[GitHubIngestedEvent]:
    for edge in edges:
        cursor = edge.get("cursor")
        node = edge.get("node")
        if not isinstance(node, dict):
            continue
        cursor_value = cursor if isinstance(cursor, str) else None
        event = _commit_event_from_node(repo, node, since, cursor=cursor_value)
        if event is not None:
            yield event


@dataclasses.dataclass(frozen=True, slots=True)
class _DocChangeSpec:
    """Computed configuration for documentation change ingestion."""

    path: str
    is_roadmap: bool
    is_adr: bool


@dataclasses.dataclass(frozen=True, slots=True)
class _DocChangePathContext:
    """Context required to paginate doc changes for a single path."""

    repo: RepositoryInfo
    path: str
    since: dt.datetime
    qualified_name: str
    cursor: str | None
    spec: _DocChangeSpec


_DOC_CURSOR_SEPARATOR = "\n"


def _decode_doc_cursor(after: str | None) -> tuple[str | None, str | None]:
    """Decode a stored doc cursor into (path, cursor) components."""
    if after is None:
        return (None, None)
    if _DOC_CURSOR_SEPARATOR not in after:
        return (None, after)
    path, cursor = after.split(_DOC_CURSOR_SEPARATOR, 1)
    return (path, cursor or None)


def _encode_doc_cursor(path: str, cursor: str | None) -> str | None:
    """Encode a doc cursor by pairing a path with a history cursor."""
    if cursor is None:
        return None
    return f"{path}{_DOC_CURSOR_SEPARATOR}{cursor}"


def _doc_change_event_from_edge(
    repo: RepositoryInfo,
    edge: dict[str, typ.Any],
    *,
    since: dt.datetime,
    spec: _DocChangeSpec,
) -> GitHubIngestedEvent | None:
    cursor = edge.get("cursor")
    node = edge.get("node")
    if not isinstance(node, dict):
        return None

    cursor_value = cursor if isinstance(cursor, str) else None
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
        cursor=_encode_doc_cursor(spec.path, cursor_value),
    )


def _iter_doc_change_events(
    repo: RepositoryInfo,
    edges: list[dict[str, typ.Any]],
    *,
    since: dt.datetime,
    spec: _DocChangeSpec,
) -> typ.Iterator[GitHubIngestedEvent]:
    for edge in edges:
        event = _doc_change_event_from_edge(
            repo,
            edge,
            since=since,
            spec=spec,
        )
        if event is not None:
            yield event


NodeToEvent = cabc.Callable[
    [RepositoryInfo, dict[str, typ.Any], dt.datetime],
    tuple[GitHubIngestedEvent | None, bool],
]


def _build_pr_payload(
    repo: RepositoryInfo,
    node: dict[str, typ.Any],
    updated_at_raw: str,
) -> dict[str, typ.Any]:
    """Build a pull request payload dict from a GraphQL node."""
    merged_at = node.get("mergedAt")
    raw_state = node.get("state")
    state = raw_state if isinstance(raw_state, str) else ""
    return {
        "number": node.get("number"),
        "title": node.get("title"),
        "author_login": _maybe_login(node.get("author")),
        "state": _coerce_pr_state(state, merged_at),
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
    updated_at_raw: str,
) -> dict[str, typ.Any]:
    """Build an issue payload dict from a GraphQL node."""
    raw_state = node.get("state")
    return {
        "number": node.get("number"),
        "title": node.get("title"),
        "author_login": _maybe_login(node.get("author")),
        "state": raw_state.lower() if isinstance(raw_state, str) else "",
        "created_at": node.get("createdAt"),
        "closed_at": node.get("closedAt"),
        "labels": _label_names(node.get("labels")),
        "repo_owner": repo.owner,
        "repo_name": repo.name,
        "metadata": {"updated_at": updated_at_raw},
    }


@dataclasses.dataclass(frozen=True, slots=True)
class _EntitySpec:
    """Configuration for a paginated GraphQL entity type."""

    query: str
    connection_path: list[str]
    entity_name: str
    node_to_event: NodeToEvent


_ENTITY_SPECS: dict[typ.Literal["pull_request", "issue"], _EntitySpec] = {
    "pull_request": _EntitySpec(
        query=_PULL_REQUESTS_QUERY,
        connection_path=["repository", "pullRequests"],
        entity_name="pull request",
        node_to_event=lambda repo, edge, since: _event_from_edge(
            repo, edge, since, kind="pull_request"
        ),
    ),
    "issue": _EntitySpec(
        query=_ISSUES_QUERY,
        connection_path=["repository", "issues"],
        entity_name="issue",
        node_to_event=lambda repo, edge, since: _event_from_edge(
            repo, edge, since, kind="issue"
        ),
    ),
}


def _next_cursor(connection: dict[str, typ.Any]) -> str | None:
    """Return the next pagination cursor, or None when pagination is complete."""
    page_info = connection.get("pageInfo")
    if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
        return None
    after_cursor = page_info.get("endCursor")
    return after_cursor if isinstance(after_cursor, str) else None


def _event_from_edge(
    repo: RepositoryInfo,
    edge: dict[str, typ.Any],
    since: dt.datetime,
    *,
    kind: typ.Literal["pull_request", "issue"],
) -> tuple[GitHubIngestedEvent | None, bool]:
    """Convert a GraphQL edge into a GitHubIngestedEvent, if applicable.

    Returns ``(event, should_stop)``, where ``should_stop`` signals that
    pagination should stop because events are now at or before the ``since``
    watermark.
    """
    raw_node = edge.get("node")
    if not isinstance(raw_node, dict):
        return (None, False)

    cursor = edge.get("cursor")
    cursor_value = cursor if isinstance(cursor, str) else None

    updated_at_raw = raw_node.get("updatedAt")
    database_id = raw_node.get("databaseId")
    if not isinstance(updated_at_raw, str) or not isinstance(database_id, int):
        return (None, False)

    updated_at = _parse_github_datetime(updated_at_raw)
    if updated_at <= since:
        return (None, True)

    payload_builder = (
        _build_pr_payload if kind == "pull_request" else _build_issue_payload
    )
    payload = payload_builder(repo, raw_node, updated_at_raw)
    payload["id"] = database_id

    event_type = "github.pull_request" if kind == "pull_request" else "github.issue"
    return (
        GitHubIngestedEvent(
            event_type=event_type,
            source_event_id=str(database_id),
            occurred_at=updated_at,
            payload=payload,
            cursor=cursor_value,
        ),
        False,
    )


def _pull_request_node_to_event(
    repo: RepositoryInfo,
    edge: dict[str, typ.Any],
    since: dt.datetime,
) -> tuple[GitHubIngestedEvent | None, bool]:
    return _event_from_edge(repo, edge, since, kind="pull_request")


def _issue_node_to_event(
    repo: RepositoryInfo,
    edge: dict[str, typ.Any],
    since: dt.datetime,
) -> tuple[GitHubIngestedEvent | None, bool]:
    return _event_from_edge(repo, edge, since, kind="issue")


def _events_from_nodes(
    repo: RepositoryInfo,
    nodes: list[dict[str, typ.Any]],
    *,
    since: dt.datetime,
    node_to_event: NodeToEvent,
) -> tuple[list[GitHubIngestedEvent], bool]:
    events: list[GitHubIngestedEvent] = []
    should_stop = False
    for node in nodes:
        event, stop = node_to_event(repo, node, since)
        if event is not None:
            events.append(event)
        if stop:
            should_stop = True
            break
    return events, should_stop


def _validate_string_keyed_dict(
    raw_dict: dict[typ.Any, typ.Any],
    *,
    field_name: str,
) -> dict[str, typ.Any]:
    """Validate that a dictionary has only string keys and return typed result.

    JSON object keys are always strings, but this validation is kept as
    defence-in-depth against malformed responses or future changes in parsing.
    """
    result: dict[str, typ.Any] = {}
    for key, value in raw_dict.items():
        if not isinstance(key, str):
            raise GitHubResponseShapeError.missing(field_name)
        result[key] = value
    return result


def _parse_graphql_payload(payload_raw: object) -> dict[str, typ.Any]:
    """Parse and validate a GraphQL response payload, extracting data field."""
    if not isinstance(payload_raw, dict):
        raise GitHubResponseShapeError.missing("response")

    payload = _validate_string_keyed_dict(payload_raw, field_name="response")

    errors = payload.get("errors")
    if errors:
        raise GitHubAPIError.graphql_errors(errors)

    data = payload.get("data")
    if not isinstance(data, dict):
        raise GitHubResponseShapeError.missing("data")

    return _validate_string_keyed_dict(data, field_name="data")


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
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        after: str | None = None,
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield commit snapshot events on the default branch."""
        since_utc = _ensure_tzaware(since, field="since")
        qualified_name = f"refs/heads/{repo.default_branch}"
        after_cursor: str | None = after

        while True:
            data = await self._graphql(
                _COMMITS_QUERY,
                {
                    "owner": repo.owner,
                    "name": repo.name,
                    "qualifiedName": qualified_name,
                    "since": since_utc.isoformat(),
                    "after": after_cursor,
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
            after_cursor = page_info.get("endCursor")
            if not isinstance(after_cursor, str):
                return

    async def _iter_paginated_entities(
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        entity_kind: typ.Literal["pull_request", "issue"],
        after: str | None = None,
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield entity snapshot events from a paginated GraphQL connection.

        This helper centralises the common pagination loop for connections
        ordered by `UPDATED_AT`, such as pull requests and issues. The
        entity-specific node-to-event callable is responsible for converting
        nodes into GitHubIngestedEvent instances and signalling when iteration
        should stop because the nodes are older than the `since` watermark.
        """
        spec = _ENTITY_SPECS[entity_kind]
        query = spec.query
        connection_path = spec.connection_path
        entity_name = spec.entity_name
        node_to_event = spec.node_to_event

        after_cursor: str | None = after
        while True:
            data = await self._graphql(
                query,
                {"owner": repo.owner, "name": repo.name, "after": after_cursor},
            )
            connection = _extract_connection(data, connection_path)
            edges = _connection_edges(connection, field=entity_name)
            events, should_stop = _events_from_nodes(
                repo,
                edges,
                since=since,
                node_to_event=node_to_event,
            )
            for event in events:
                yield event
            if should_stop:
                return

            after_cursor = _next_cursor(connection)
            if after_cursor is None:
                return

    async def iter_pull_requests(
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        after: str | None = None,
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield pull request snapshot events updated since a timestamp."""
        since_utc = _ensure_tzaware(since, field="since")
        async for event in self._iter_paginated_entities(
            repo,
            since=since_utc,
            entity_kind="pull_request",
            after=after,
        ):
            yield event

    async def iter_issues(
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        after: str | None = None,
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield issue snapshot events updated since a timestamp."""
        since_utc = _ensure_tzaware(since, field="since")
        async for event in self._iter_paginated_entities(
            repo,
            since=since_utc,
            entity_kind="issue",
            after=after,
        ):
            yield event

    async def _iter_doc_changes_for_path(
        self, context: _DocChangePathContext
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield documentation change events for a single path with pagination."""
        path_cursor = context.cursor
        while True:
            data = await self._graphql(
                _COMMITS_QUERY,
                {
                    "owner": context.repo.owner,
                    "name": context.repo.name,
                    "qualifiedName": context.qualified_name,
                    "since": context.since.isoformat(),
                    "after": path_cursor,
                    "path": context.path,
                },
            )
            history = _extract_commit_history(data)
            edges = _connection_edges(history, field="doc change commit history")
            for event in _iter_doc_change_events(
                context.repo, edges, since=context.since, spec=context.spec
            ):
                yield event

            page_info = history.get("pageInfo")
            if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
                break
            path_cursor = page_info.get("endCursor")
            if not isinstance(path_cursor, str):
                break

    async def iter_doc_changes(
        self,
        repo: RepositoryInfo,
        *,
        since: dt.datetime,
        documentation_paths: typ.Sequence[str],
        after: str | None = None,
    ) -> typ.AsyncIterator[GitHubIngestedEvent]:
        """Yield documentation change events for documentation path commits."""
        since_utc = _ensure_tzaware(since, field="since")
        qualified_name = f"refs/heads/{repo.default_branch}"
        resume_path, resume_cursor = _decode_doc_cursor(after)

        for path in documentation_paths:
            # If resuming, skip earlier paths; apply the resume cursor once on the
            # matching path then clear resume state so subsequent paths start fresh.
            if resume_path is not None and path != resume_path:
                continue
            path_cursor, resume_cursor = resume_cursor, None
            resume_path = None
            is_roadmap, is_adr = _classify_documentation_path(path)
            spec = _DocChangeSpec(path=path, is_roadmap=is_roadmap, is_adr=is_adr)
            context = _DocChangePathContext(
                repo=repo,
                path=path,
                since=since_utc,
                qualified_name=qualified_name,
                cursor=path_cursor,
                spec=spec,
            )
            async for event in self._iter_doc_changes_for_path(context):
                yield event

    async def _graphql(
        self, query: str, variables: dict[str, typ.Any]
    ) -> dict[str, typ.Any]:
        """Execute a GraphQL query and return the validated data field."""
        response = await self._client.post(
            self._config.endpoint,
            json={"query": query, "variables": variables},
        )
        if response.status_code >= _HTTP_ERROR_STATUS_THRESHOLD:
            raise GitHubAPIError.http_error(response.status_code)
        payload_raw = response.json()
        return _parse_graphql_payload(payload_raw)


def _traverse_path(data: dict[str, typ.Any], path: list[str]) -> object:
    """Traverse a nested dictionary path, validating each step."""
    node: object = data
    for key in path:
        if not isinstance(node, dict):
            raise GitHubResponseShapeError.missing(".".join(path))
        node = node.get(key)
    return node


def _validate_and_copy_dict(node: object, path: list[str]) -> dict[str, typ.Any]:
    """Validate that node is a dict with string keys and return a copy."""
    if not isinstance(node, dict):
        raise GitHubResponseShapeError.missing(".".join(path))

    result: dict[str, typ.Any] = {}
    for key, value in node.items():
        if not isinstance(key, str):
            raise GitHubResponseShapeError.missing(".".join(path))
        result[key] = value
    return result


def _extract_connection(
    data: dict[str, typ.Any], path: list[str]
) -> dict[str, typ.Any]:
    """Extract a connection from nested GraphQL response data."""
    node = _traverse_path(data, path)
    return _validate_and_copy_dict(node, path)


def _extract_commit_history(data: dict[str, typ.Any]) -> dict[str, typ.Any]:
    """Extract commit history from GraphQL response data."""
    return _extract_connection(data, ["repository", "ref", "target", "history"])
