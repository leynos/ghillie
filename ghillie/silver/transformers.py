"""Entity-level Silver transformers for GitHub raw events."""

from __future__ import annotations

import copy
import datetime as dt
import typing as typ

import msgspec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ghillie.bronze.storage import RawEvent
from ghillie.silver.errors import RawEventTransformError
from ghillie.silver.storage import (
    Commit,
    DocumentationChange,
    Issue,
    PullRequest,
    Repository,
)

EntityTransformer = typ.Callable[[AsyncSession, RawEvent], typ.Awaitable[None]]
_registry: dict[str, EntityTransformer] = {}


def register(event_type: str) -> typ.Callable[[EntityTransformer], EntityTransformer]:
    """Register an entity transformer."""

    def _inner(func: EntityTransformer) -> EntityTransformer:
        _registry[event_type] = func
        return func

    return _inner


def get_entity_transformer(event_type: str) -> EntityTransformer | None:
    """Return a registered transformer for the event type if present."""
    return _registry.get(event_type)


class GithubCommitPayload(msgspec.Struct, frozen=True, omit_defaults=True):
    """Typed payload for commit raw events."""

    sha: str
    repo_owner: str
    repo_name: str
    message: str | None = None
    author_email: str | None = None
    author_name: str | None = None
    authored_at: str | None = None
    committed_at: str | None = None
    default_branch: str | None = None
    metadata: dict[str, typ.Any] | None = None


class GithubPullRequestPayload(msgspec.Struct, frozen=True, omit_defaults=True):
    """Typed payload for pull request raw events."""

    id: int
    number: int
    title: str
    state: str
    base_branch: str
    head_branch: str
    repo_owner: str
    repo_name: str
    created_at: str
    author_login: str | None = None
    merged_at: str | None = None
    closed_at: str | None = None
    labels: list[str] | None = None
    is_draft: bool = False
    metadata: dict[str, typ.Any] | None = None


class GithubIssuePayload(msgspec.Struct, frozen=True, omit_defaults=True):
    """Typed payload for issue raw events."""

    id: int
    number: int
    title: str
    state: str
    repo_owner: str
    repo_name: str
    created_at: str
    author_login: str | None = None
    closed_at: str | None = None
    labels: list[str] | None = None
    metadata: dict[str, typ.Any] | None = None


class GithubDocumentationChangePayload(msgspec.Struct, frozen=True, omit_defaults=True):
    """Typed payload for documentation change raw events."""

    commit_sha: str
    path: str
    change_type: str
    repo_owner: str
    repo_name: str
    occurred_at: str
    is_roadmap: bool = False
    is_adr: bool = False
    metadata: dict[str, typ.Any] | None = None


def _decode_payload[PayloadT: msgspec.Struct](
    raw: RawEvent, model: type[PayloadT]
) -> PayloadT:
    """Decode a Bronze payload into the provided msgspec struct."""
    try:
        return msgspec.convert(raw.payload, type=model)
    except msgspec.ValidationError as exc:
        raise RawEventTransformError.invalid_payload(str(exc)) from exc


def _normalise_datetime(
    value: dt.datetime | str | None, field_name: str
) -> dt.datetime | None:
    """Parse ISO strings or ensure aware datetimes."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return _handle_datetime_object(value, field_name)
    if isinstance(value, str):
        return _handle_datetime_string(value, field_name)
    raise RawEventTransformError.unsupported_datetime_type(field_name)


def _handle_datetime_object(value: dt.datetime, field_name: str) -> dt.datetime:
    """Validate and normalise aware datetime objects."""
    if value.tzinfo is None:
        raise RawEventTransformError.datetime_requires_timezone(field_name)
    return value.astimezone(dt.UTC)


def _handle_datetime_string(value: str, field_name: str) -> dt.datetime:
    """Parse and normalise ISO-8601 datetime strings."""
    text = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise RawEventTransformError.invalid_datetime_format(field_name) from exc
    if parsed.tzinfo is None:
        raise RawEventTransformError.missing_datetime_timezone(field_name)
    return parsed.astimezone(dt.UTC)


def _copy_metadata(metadata: dict[str, typ.Any] | None) -> dict[str, typ.Any]:
    """Return a deep-copied metadata dict."""
    return {} if metadata is None else copy.deepcopy(metadata)


async def _ensure_repository(
    session: AsyncSession, owner: str, name: str, default_branch: str | None
) -> Repository:
    """Fetch or create a repository row.

    Repositories created ad hoc (not synced from catalogue) have ingestion
    disabled by default to prevent uncontrolled event processing. Use the
    RepositoryRegistryService to sync catalogue repositories and enable
    ingestion.
    """
    repo = await session.scalar(
        select(Repository).where(
            Repository.github_owner == owner, Repository.github_name == name
        )
    )
    if repo is None:
        repo = Repository(
            github_owner=owner,
            github_name=name,
            default_branch=default_branch or "main",
            # Ad hoc repos have ingestion disabled until synced from catalogue
            catalogue_repository_id=None,
            ingestion_enabled=False,
        )
        session.add(repo)
        await session.flush()
        return repo

    if default_branch and repo.default_branch != default_branch:
        repo.default_branch = default_branch
    return repo


def _assert_repo_match(existing_repo_id: str, repo: Repository) -> None:
    """Ensure foreign keys do not drift across repositories."""
    if existing_repo_id != repo.id:
        raise RawEventTransformError.repository_mismatch()


async def _upsert_commit(
    session: AsyncSession, repo: Repository, payload: GithubCommitPayload
) -> Commit:
    """Insert or update a commit row."""
    metadata = _copy_metadata(payload.metadata)
    authored_at = _normalise_datetime(payload.authored_at, "authored_at")
    committed_at = _normalise_datetime(payload.committed_at, "committed_at")

    existing = await session.get(Commit, payload.sha)
    if existing is None:
        commit = Commit(
            sha=payload.sha,
            repo_id=repo.id,
            author_email=payload.author_email,
            author_name=payload.author_name,
            authored_at=authored_at,
            committed_at=committed_at,
            message=payload.message,
            metadata_=metadata,
        )
        session.add(commit)
        return commit

    _assert_repo_match(existing.repo_id, repo)
    existing.author_email = payload.author_email or existing.author_email
    existing.author_name = payload.author_name or existing.author_name
    existing.authored_at = authored_at or existing.authored_at
    existing.committed_at = committed_at or existing.committed_at
    existing.message = payload.message or existing.message
    if payload.metadata is not None:
        existing.metadata_ = metadata
    return existing


async def _upsert_pull_request(
    session: AsyncSession, repo: Repository, payload: GithubPullRequestPayload
) -> PullRequest:
    """Insert or update a pull request row."""
    metadata = _copy_metadata(payload.metadata)
    created_at = _normalise_datetime(payload.created_at, "created_at")
    merged_at = _normalise_datetime(payload.merged_at, "merged_at")
    closed_at = _normalise_datetime(payload.closed_at, "closed_at")
    labels = payload.labels

    existing = await session.get(PullRequest, payload.id)
    if existing is None:
        pr = PullRequest(
            id=payload.id,
            repo_id=repo.id,
            number=payload.number,
            title=payload.title,
            author_login=payload.author_login,
            state=payload.state,
            merged_at=merged_at,
            closed_at=closed_at,
            created_at=created_at,
            labels=labels if labels is not None else [],
            is_draft=payload.is_draft,
            base_branch=payload.base_branch,
            head_branch=payload.head_branch,
            metadata_=metadata,
        )
        session.add(pr)
        return pr

    _assert_repo_match(existing.repo_id, repo)
    existing.number = payload.number
    existing.title = payload.title
    existing.author_login = payload.author_login
    existing.state = payload.state
    existing.merged_at = merged_at
    existing.closed_at = closed_at
    existing.created_at = created_at or existing.created_at
    if labels is not None:
        existing.labels = labels
    existing.is_draft = payload.is_draft
    existing.base_branch = payload.base_branch
    existing.head_branch = payload.head_branch
    if payload.metadata is not None:
        existing.metadata_ = metadata
    return existing


async def _upsert_issue(
    session: AsyncSession, repo: Repository, payload: GithubIssuePayload
) -> Issue:
    """Insert or update an issue row."""
    metadata = _copy_metadata(payload.metadata)
    created_at = _normalise_datetime(payload.created_at, "created_at")
    closed_at = _normalise_datetime(payload.closed_at, "closed_at")
    labels = payload.labels

    existing = await session.get(Issue, payload.id)
    if existing is None:
        issue = Issue(
            id=payload.id,
            repo_id=repo.id,
            number=payload.number,
            title=payload.title,
            author_login=payload.author_login,
            state=payload.state,
            created_at=created_at,
            closed_at=closed_at,
            labels=labels if labels is not None else [],
            metadata_=metadata,
        )
        session.add(issue)
        return issue

    _assert_repo_match(existing.repo_id, repo)
    existing.number = payload.number
    existing.title = payload.title
    existing.author_login = payload.author_login
    existing.state = payload.state
    existing.created_at = created_at or existing.created_at
    existing.closed_at = closed_at
    if labels is not None:
        existing.labels = labels
    if payload.metadata is not None:
        existing.metadata_ = metadata
    return existing


async def _ensure_commit_stub(
    session: AsyncSession, repo: Repository, commit_sha: str
) -> Commit:
    """Ensure a commit row exists so doc changes can reference it."""
    existing = await session.get(Commit, commit_sha)
    if existing is not None:
        _assert_repo_match(existing.repo_id, repo)
        return existing

    commit = Commit(
        sha=commit_sha,
        repo_id=repo.id,
        metadata_={},
    )
    session.add(commit)
    await session.flush()
    return commit


async def _upsert_documentation_change(
    session: AsyncSession,
    repo: Repository,
    payload: GithubDocumentationChangePayload,
) -> DocumentationChange:
    """Insert or update documentation change rows keyed by commit+path."""
    occurred_at = _normalise_datetime(payload.occurred_at, "occurred_at")
    if occurred_at is None:
        raise RawEventTransformError.occurred_at_required()
    metadata = _copy_metadata(payload.metadata)
    await _ensure_commit_stub(session, repo, payload.commit_sha)

    existing = await session.scalar(
        select(DocumentationChange).where(
            DocumentationChange.repo_id == repo.id,
            DocumentationChange.commit_sha == payload.commit_sha,
            DocumentationChange.path == payload.path,
        )
    )
    if existing is None:
        doc_change = DocumentationChange(
            repo_id=repo.id,
            commit_sha=payload.commit_sha,
            path=payload.path,
            change_type=payload.change_type,
            is_roadmap=payload.is_roadmap,
            is_adr=payload.is_adr,
            metadata_=metadata,
            occurred_at=occurred_at,
        )
        session.add(doc_change)
        return doc_change

    existing.change_type = payload.change_type
    existing.is_roadmap = payload.is_roadmap
    existing.is_adr = payload.is_adr
    if payload.metadata is not None:
        existing.metadata_ = metadata
    existing.occurred_at = occurred_at or existing.occurred_at
    return existing


@register("github.commit")
async def transform_github_commit(session: AsyncSession, raw_event: RawEvent) -> None:
    """Hydrate repositories and commits from commit raw events."""
    payload = _decode_payload(raw_event, GithubCommitPayload)
    repo = await _ensure_repository(
        session, payload.repo_owner, payload.repo_name, payload.default_branch
    )
    await _upsert_commit(session, repo, payload)


@register("github.pull_request")
async def transform_github_pull_request(
    session: AsyncSession, raw_event: RawEvent
) -> None:
    """Hydrate repositories and pull requests from PR raw events."""
    payload = _decode_payload(raw_event, GithubPullRequestPayload)
    repo = await _ensure_repository(
        session, payload.repo_owner, payload.repo_name, None
    )
    await _upsert_pull_request(session, repo, payload)


@register("github.issue")
async def transform_github_issue(session: AsyncSession, raw_event: RawEvent) -> None:
    """Hydrate repositories and issues from issue raw events."""
    payload = _decode_payload(raw_event, GithubIssuePayload)
    repo = await _ensure_repository(
        session, payload.repo_owner, payload.repo_name, None
    )
    await _upsert_issue(session, repo, payload)


@register("github.doc_change")
async def transform_github_doc_change(
    session: AsyncSession, raw_event: RawEvent
) -> None:
    """Hydrate documentation changes from raw events."""
    payload = _decode_payload(raw_event, GithubDocumentationChangePayload)
    repo = await _ensure_repository(
        session, payload.repo_owner, payload.repo_name, None
    )
    await _upsert_documentation_change(session, repo, payload)
