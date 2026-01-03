"""Behavioural tests for evidence bundle generation."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

from pytest_bdd import given, scenario, then, when
from sqlalchemy import select

from ghillie.bronze import RawEventEnvelope, RawEventWriter
from ghillie.evidence import (
    EvidenceBundleService,
    ReportStatus,
    RepositoryEvidenceBundle,
    WorkType,
)
from ghillie.gold import Report, ReportScope
from ghillie.silver import RawEventTransformer, Repository
from tests.helpers.event_builders import (
    DocChangeEventSpec,
    IssueEventSpec,
    PREventSpec,
    commit_envelope,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class EvidenceContext(typ.TypedDict, total=False):
    """Mutable context shared between steps."""

    session_factory: async_sessionmaker[AsyncSession]
    writer: RawEventWriter
    transformer: RawEventTransformer
    service: EvidenceBundleService
    repo_slug: str
    repo_id: str
    window_start: dt.datetime
    window_end: dt.datetime
    bundle: RepositoryEvidenceBundle


# Scenario wrappers


@scenario(
    "../evidence_bundle.feature", "Build evidence bundle for repository with activity"
)
def test_build_evidence_bundle_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


@scenario("../evidence_bundle.feature", "Bundle includes previous report context")
def test_bundle_previous_report_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


@scenario("../evidence_bundle.feature", "Work type classification from labels")
def test_classification_from_labels_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


@scenario("../evidence_bundle.feature", "Work type classification from title patterns")
def test_classification_from_title_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _setup_repo_from_events(
    evidence_context: EvidenceContext,
    events: list[RawEventEnvelope],
) -> None:
    """Ingest events, process with transformer, and set repo_id in context."""
    writer = evidence_context["writer"]
    transformer = evidence_context["transformer"]

    for event in events:
        await writer.ingest(event)
    await transformer.process_pending()

    async with evidence_context["session_factory"]() as session:
        repo = await session.scalar(select(Repository))
        assert repo is not None
        evidence_context["repo_id"] = repo.id


# Given steps


@given("an empty store for evidence bundles", target_fixture="evidence_context")
def given_empty_store(
    session_factory: async_sessionmaker[AsyncSession],
) -> EvidenceContext:
    """Provision services backed by a fresh database."""
    return {
        "session_factory": session_factory,
        "writer": RawEventWriter(session_factory),
        "transformer": RawEventTransformer(session_factory),
        "service": EvidenceBundleService(session_factory),
        "repo_slug": "octo/reef",
        "window_start": dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        "window_end": dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
    }


@given('a repository "octo/reef" with ingested GitHub events')
def given_repo_with_events(evidence_context: EvidenceContext) -> None:
    """Ingest a variety of GitHub events for the repository."""
    repo_slug = evidence_context["repo_slug"]

    # Commit
    commit_time = dt.datetime(2024, 7, 3, 10, 0, tzinfo=dt.UTC)
    # Pull request
    pr_time = dt.datetime(2024, 7, 4, tzinfo=dt.UTC)
    # Issue
    issue_time = dt.datetime(2024, 7, 5, tzinfo=dt.UTC)
    # Documentation change
    doc_time = dt.datetime(2024, 7, 6, tzinfo=dt.UTC)

    events = [
        commit_envelope(repo_slug, "abc123", commit_time, "feat: add auth"),
        PREventSpec(
            repo_slug=repo_slug,
            pr_id=100,
            pr_number=10,
            created_at=pr_time,
            title="Add login feature",
        ).build(),
        IssueEventSpec(
            repo_slug=repo_slug,
            issue_id=200,
            issue_number=20,
            created_at=issue_time,
            title="Bug report",
        ).build(),
        commit_envelope(repo_slug, "doc456", doc_time),
        DocChangeEventSpec(
            repo_slug=repo_slug,
            commit_sha="doc456",
            path="docs/roadmap.md",
            occurred_at=doc_time,
            is_roadmap=True,
        ).build(),
    ]

    asyncio.run(_setup_repo_from_events(evidence_context, events))


@given('a repository "octo/reef" with a previous report')
def given_repo_with_previous_report(evidence_context: EvidenceContext) -> None:
    """Create a repository with a previous report."""
    repo_slug = evidence_context["repo_slug"]

    # Commit to establish repo
    commit_time = dt.datetime(2024, 7, 10, tzinfo=dt.UTC)
    events = [commit_envelope(repo_slug, "abc123", commit_time)]

    async def _setup_with_report() -> None:
        await _setup_repo_from_events(evidence_context, events)

        # Create previous report
        async with evidence_context["session_factory"]() as session:
            prev_report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=evidence_context["repo_id"],
                window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                model="test-model",
                machine_summary={
                    "status": "on_track",
                    "highlights": ["Shipped v1.0", "Fixed critical bug"],
                    "risks": ["Tech debt increasing"],
                },
            )
            session.add(prev_report)
            await session.commit()

    asyncio.run(_setup_with_report())

    # Update window for next report
    evidence_context["window_start"] = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)
    evidence_context["window_end"] = dt.datetime(2024, 7, 15, tzinfo=dt.UTC)


@given('a repository "octo/reef" with a pull request labelled "bug"')
def given_repo_with_bug_pr(evidence_context: EvidenceContext) -> None:
    """Create a repository with a bug-labelled PR."""
    repo_slug = evidence_context["repo_slug"]
    pr_time = dt.datetime(2024, 7, 5, tzinfo=dt.UTC)

    events = [
        PREventSpec(
            repo_slug=repo_slug,
            pr_id=100,
            pr_number=10,
            created_at=pr_time,
            title="Fix login issue",
            labels=("bug",),
        ).build(),
    ]

    asyncio.run(_setup_repo_from_events(evidence_context, events))


@given('a repository "octo/reef" with a commit message "fix: resolve login issue"')
def given_repo_with_fix_commit(evidence_context: EvidenceContext) -> None:
    """Create a repository with a fix commit."""
    repo_slug = evidence_context["repo_slug"]
    commit_time = dt.datetime(2024, 7, 5, tzinfo=dt.UTC)

    events = [
        commit_envelope(repo_slug, "fix123", commit_time, "fix: resolve login issue"),
    ]

    asyncio.run(_setup_repo_from_events(evidence_context, events))


# When steps


async def _build_bundle_async(evidence_context: EvidenceContext) -> None:
    """Build the evidence bundle and store it in context."""
    service = evidence_context["service"]
    repo_id = evidence_context["repo_id"]
    window_start = evidence_context["window_start"]
    window_end = evidence_context["window_end"]

    bundle = await service.build_bundle(repo_id, window_start, window_end)
    evidence_context["bundle"] = bundle


@when('I build an evidence bundle for "octo/reef" for the reporting window')
def when_build_bundle(evidence_context: EvidenceContext) -> None:
    """Build the evidence bundle."""
    asyncio.run(_build_bundle_async(evidence_context))


@when("I build an evidence bundle for the next window")
def when_build_bundle_next_window(evidence_context: EvidenceContext) -> None:
    """Build the evidence bundle for the next window."""
    asyncio.run(_build_bundle_async(evidence_context))


# Then steps


@then("the bundle contains the repository metadata")
def then_bundle_has_metadata(evidence_context: EvidenceContext) -> None:
    """Assert bundle contains repository metadata."""
    bundle = evidence_context["bundle"]

    assert bundle.repository.slug == "octo/reef"
    assert bundle.repository.owner == "octo"
    assert bundle.repository.name == "reef"
    assert bundle.repository.default_branch == "main"


@then("the bundle contains commits within the window")
def then_bundle_has_commits(evidence_context: EvidenceContext) -> None:
    """Assert bundle contains commits."""
    bundle = evidence_context["bundle"]

    # Assert that the bundle's reporting window matches the requested window
    assert bundle.window_start == evidence_context["window_start"]
    assert bundle.window_end == evidence_context["window_end"]

    assert len(bundle.commits) >= 1
    # Check that commits are within window
    for commit in bundle.commits:
        if commit.committed_at is not None:
            assert commit.committed_at >= evidence_context["window_start"]
            assert commit.committed_at < evidence_context["window_end"]


@then("the bundle contains pull requests within the window")
def then_bundle_has_prs(evidence_context: EvidenceContext) -> None:
    """Assert bundle contains pull requests."""
    bundle = evidence_context["bundle"]

    assert len(bundle.pull_requests) >= 1


@then("the bundle contains issues within the window")
def then_bundle_has_issues(evidence_context: EvidenceContext) -> None:
    """Assert bundle contains issues."""
    bundle = evidence_context["bundle"]

    assert len(bundle.issues) >= 1


@then("the bundle contains documentation changes within the window")
def then_bundle_has_doc_changes(evidence_context: EvidenceContext) -> None:
    """Assert bundle contains documentation changes."""
    bundle = evidence_context["bundle"]

    assert len(bundle.documentation_changes) >= 1
    assert any(dc.is_roadmap for dc in bundle.documentation_changes)


@then("the bundle contains work type groupings")
def then_bundle_has_groupings(evidence_context: EvidenceContext) -> None:
    """Assert bundle contains work type groupings."""
    bundle = evidence_context["bundle"]

    assert len(bundle.work_type_groupings) >= 1
    # At least one grouping should have events
    assert any(
        g.commit_count > 0 or g.pr_count > 0 or g.issue_count > 0
        for g in bundle.work_type_groupings
    )


@then("the bundle contains the previous report summary")
def then_bundle_has_previous_report(evidence_context: EvidenceContext) -> None:
    """Assert bundle contains previous report."""
    bundle = evidence_context["bundle"]

    assert bundle.has_previous_context is True
    assert len(bundle.previous_reports) >= 1


@then("the previous report summary includes status and highlights")
def then_previous_report_has_status(evidence_context: EvidenceContext) -> None:
    """Assert previous report has status and highlights."""
    bundle = evidence_context["bundle"]

    prev = bundle.previous_reports[0]
    assert prev.status == ReportStatus.ON_TRACK
    assert "Shipped v1.0" in prev.highlights
    assert "Tech debt increasing" in prev.risks


@then('the pull request is classified as "bug"')
def then_pr_classified_as_bug(evidence_context: EvidenceContext) -> None:
    """Assert PR is classified as bug."""
    bundle = evidence_context["bundle"]

    assert len(bundle.pull_requests) == 1
    assert bundle.pull_requests[0].work_type == WorkType.BUG


@then('the commit is classified as "bug"')
def then_commit_classified_as_bug(evidence_context: EvidenceContext) -> None:
    """Assert commit is classified as bug."""
    bundle = evidence_context["bundle"]

    assert len(bundle.commits) == 1
    assert bundle.commits[0].work_type == WorkType.BUG
