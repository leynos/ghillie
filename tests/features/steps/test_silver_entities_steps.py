"""Behavioural coverage for Silver entity table hydration."""

from __future__ import annotations

import dataclasses as dc
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
from tests.helpers import run_async

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SilverContext(typ.TypedDict, total=False):
    """Shared mutable scenario state."""

    session_factory: async_sessionmaker[AsyncSession]
    writer: RawEventWriter
    transformer: RawEventTransformer
    repo_slug: str
    commit_sha: str
    ingested_envelopes: list[RawEventEnvelope]
    counts_before_replay: dict[str, int]
    snapshots_before_replay: dict[str, list[tuple]]


@scenario(
    "../silver_entities.feature",
    "GitHub entity events hydrate Silver tables",
)
def test_silver_entity_hydration() -> None:
    """Wrap the pytest-bdd scenario."""


@scenario(
    "../silver_entities.feature",
    "GitHub entity events are idempotent on replay",
)
def test_silver_entity_hydration_idempotent_replay() -> None:
    """Verify Bronze→Silver hydration is idempotent when events are replayed."""


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
        "ingested_envelopes": [],
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
        envelopes = [
            _create_commit_event(repo_slug, commit_sha, occurred_at),
            _create_pull_request_event(repo_slug, occurred_at),
            _create_issue_event(repo_slug, occurred_at),
            _create_doc_change_event(repo_slug, commit_sha, occurred_at),
        ]
        for envelope in envelopes:
            await writer.ingest(envelope)
        silver_context["ingested_envelopes"] = envelopes

    run_async(_run)


@when("I transform pending raw events for Silver entities")
def transform_pending_events(silver_context: SilverContext) -> None:
    """Run the Bronze→Silver transformation."""
    run_async(silver_context["transformer"].process_pending)


@when("the Silver transformer runs again on the same events")
def rerun_transformer_on_same_events(silver_context: SilverContext) -> None:
    """Reprocess the same ingested events to assert idempotency."""
    writer = silver_context["writer"]
    envelopes = silver_context.get("ingested_envelopes", [])

    async def _run() -> None:
        async with silver_context["session_factory"]() as session:
            silver_context["counts_before_replay"] = await _snapshot_counts(session)
            silver_context["snapshots_before_replay"] = await _snapshot_entities(
                session
            )
        for envelope in envelopes:
            await writer.ingest(envelope)
        await silver_context["transformer"].process_pending()

    run_async(_run)


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
            assert repo is not None, 'expected repo "octo/reef" to exist'
            assert repo.default_branch == "main", "expected default_branch to be 'main'"

    run_async(_assert)


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
            assert repo is not None, 'expected repo "octo/reef" to exist'
            commit = await session.get(Commit, silver_context["commit_sha"])
            assert commit is not None, (
                f"expected commit {silver_context['commit_sha']} to exist"
            )
            assert commit.repo_id == repo.id, (
                f"commit {commit.sha} should be linked to repo {repo.id}"
            )
            assert commit.message == "docs: flesh out roadmap", (
                "expected commit message to be 'docs: flesh out roadmap'"
            )

    run_async(_assert)


@dc.dataclass
class ExpectedEntityState:
    """Expected state for entity assertion."""

    entity_type: type[PullRequest] | type[Issue]
    entity_id: int
    expected_state: str
    expected_labels: list[str]


def _assert_entity_with_state_and_labels(
    silver_context: SilverContext, expected: ExpectedEntityState
) -> None:
    """Assert an entity exists with expected state and labels."""

    async def _assert() -> None:
        async with silver_context["session_factory"]() as session:
            entity = await session.get(expected.entity_type, expected.entity_id)
            assert entity is not None, (
                f"expected entity id {expected.entity_id} to exist"
            )
            assert entity.repo_id is not None, (
                f"entity {expected.entity_id} should have a repo_id"
            )
            assert entity.state == expected.expected_state, (
                f"expected state {expected.expected_state}"
            )
            assert entity.labels == expected.expected_labels, (
                f"expected labels {expected.expected_labels}"
            )

    run_async(_assert)


@then('the Silver pull requests table includes number 17 for "octo/reef"')
def assert_pull_request_exists(silver_context: SilverContext) -> None:
    """Verify the pull request row exists and is linked."""
    _assert_entity_with_state_and_labels(
        silver_context,
        ExpectedEntityState(
            PullRequest,
            17,
            "merged",
            ["feature", "roadmap"],
        ),
    )


@then('the Silver issues table includes number 5 for "octo/reef"')
def assert_issue_exists(silver_context: SilverContext) -> None:
    """Verify the issue row exists and is linked."""
    _assert_entity_with_state_and_labels(
        silver_context,
        ExpectedEntityState(
            Issue,
            5,
            "closed",
            ["documentation"],
        ),
    )


async def _snapshot_counts(session: AsyncSession) -> dict[str, int]:
    """Capture per-entity counts for idempotency checks."""
    repositories = len((await session.scalars(select(Repository))).all())
    commits = len((await session.scalars(select(Commit))).all())
    prs = len((await session.scalars(select(PullRequest))).all())
    issues = len((await session.scalars(select(Issue))).all())
    docs = len((await session.scalars(select(DocumentationChange))).all())
    return {
        "repositories": repositories,
        "commits": commits,
        "pull_requests": prs,
        "issues": issues,
        "documentation_changes": docs,
    }


async def _snapshot_entities(session: AsyncSession) -> dict[str, list[tuple]]:
    """Capture stable snapshots of entity state for idempotency checks."""
    repo_snap = [
        (repo.github_owner, repo.github_name, repo.default_branch, repo.is_active)
        for repo in (
            await session.scalars(
                select(Repository).order_by(
                    Repository.github_owner, Repository.github_name
                )
            )
        ).all()
    ]
    commit_snap = [
        (commit.sha, commit.repo_id, commit.message, commit.metadata_)
        for commit in (await session.scalars(select(Commit).order_by(Commit.sha))).all()
    ]
    pr_snap = [
        (
            pr.id,
            pr.repo_id,
            pr.state,
            pr.labels,
            pr.metadata_,
            pr.merged_at,
            pr.closed_at,
        )
        for pr in (
            await session.scalars(select(PullRequest).order_by(PullRequest.id))
        ).all()
    ]
    issue_snap = [
        (issue.id, issue.repo_id, issue.state, issue.labels, issue.metadata_)
        for issue in (await session.scalars(select(Issue).order_by(Issue.id))).all()
    ]
    doc_snap = [
        (
            doc.id,
            doc.repo_id,
            doc.commit_sha,
            doc.path,
            doc.change_type,
            doc.metadata_,
            doc.occurred_at,
        )
        for doc in (
            await session.scalars(
                select(DocumentationChange).order_by(DocumentationChange.id)
            )
        ).all()
    ]
    return {
        "repositories": repo_snap,
        "commits": commit_snap,
        "pull_requests": pr_snap,
        "issues": issue_snap,
        "documentation_changes": doc_snap,
    }


@then("the Silver entity counts do not increase")
def assert_entity_counts_stable(silver_context: SilverContext) -> None:
    """Ensure replay does not create extra rows."""

    async def _assert() -> None:
        async with silver_context["session_factory"]() as session:
            counts_after = await _snapshot_counts(session)
        assert counts_after == silver_context["counts_before_replay"], (
            "counts should remain unchanged after replay"
        )

    run_async(_assert)


@then("the Silver entity state and metadata remain unchanged")
def assert_entity_state_stable(silver_context: SilverContext) -> None:
    """Ensure replay leaves entity state unchanged."""

    async def _assert() -> None:
        async with silver_context["session_factory"]() as session:
            snapshots_after = await _snapshot_entities(session)
        assert snapshots_after == silver_context["snapshots_before_replay"], (
            "snapshots should remain unchanged after replay"
        )

    run_async(_assert)


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
            assert doc_change is not None, (
                'expected documentation change for path "docs/roadmap.md"'
            )
            assert doc_change.is_roadmap is True, (
                "expected documentation change to be marked as roadmap"
            )
            assert doc_change.is_adr is False, (
                "expected documentation change to not be marked as ADR"
            )

    run_async(_assert)
