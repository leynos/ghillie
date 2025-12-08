"""Behavioural coverage for Gold report metadata and coverage tables."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

from pytest_bdd import given, scenario, then, when
from sqlalchemy import select

from ghillie.bronze import RawEventEnvelope, RawEventWriter
from ghillie.gold import Report, ReportCoverage, ReportProject, ReportScope
from ghillie.silver import EventFact, RawEventTransformer, Repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class GoldContext(typ.TypedDict, total=False):
    """Mutable context shared between steps."""

    session_factory: async_sessionmaker[AsyncSession]
    writer: RawEventWriter
    transformer: RawEventTransformer
    repo_slug: str
    commit_sha: str
    report_id: str
    project_id: str
    window_start: dt.datetime
    window_end: dt.datetime


@scenario("../gold_reports.feature", "Repository report links scope and coverage")
def test_repository_report_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


@scenario("../gold_reports.feature", "Project report stores machine summary")
def test_project_report_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


@given(
    "an empty Bronze, Silver, and Gold store for reports",
    target_fixture="gold_context",
)
def given_empty_store(session_factory: async_sessionmaker[AsyncSession]) -> GoldContext:
    """Provision a writer and transformer backed by a fresh database."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    return {
        "session_factory": session_factory,
        "writer": writer,
        "transformer": transformer,
        "repo_slug": "octo/reef",
        "commit_sha": "abc123",
        "window_start": dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        "window_end": dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
    }


def _commit_envelope(
    repo_slug: str, commit_sha: str, occurred_at: dt.datetime
) -> RawEventEnvelope:
    """Construct a commit event envelope used in repository-scope tests.

    Args:
        repo_slug: Repository identifier in 'owner/name' format.
        commit_sha: Commit SHA to embed in the envelope.
        occurred_at: Timezone-aware timestamp for the event.

    Raises:
        ValueError: If repo_slug is not in 'owner/name' format.

    """
    if repo_slug.count("/") != 1:
        msg = f"Expected 'owner/name' format, got: {repo_slug}"
        raise ValueError(msg)
    owner, name = repo_slug.split("/")
    return RawEventEnvelope(
        source_system="github",
        source_event_id="commit-gold",
        event_type="github.commit",
        repo_external_id=repo_slug,
        occurred_at=occurred_at,
        payload={
            "sha": commit_sha,
            "message": "add gold schema",
            "author_email": "dev@example.com",
            "author_name": "Marina",
            "authored_at": "2024-07-06T10:00:00Z",
            "committed_at": "2024-07-06T10:05:00Z",
            "repo_owner": owner,
            "repo_name": name,
            "default_branch": "main",
            "metadata": {"ref": "refs/heads/main"},
        },
    )


@when("I create a repository report covering new GitHub events")
def when_create_repository_report(gold_context: GoldContext) -> None:
    """Ingest a commit event and attach it to a repository-scoped report."""
    occurred_at = dt.datetime(2024, 7, 6, 10, 5, tzinfo=dt.UTC)

    async def _run() -> None:
        writer = gold_context["writer"]
        transformer = gold_context["transformer"]
        repo_slug = gold_context["repo_slug"]
        commit_sha = gold_context["commit_sha"]

        await writer.ingest(_commit_envelope(repo_slug, commit_sha, occurred_at))
        await transformer.process_pending()

        async with gold_context["session_factory"]() as session:
            repo = await session.scalar(select(Repository))
            assert repo is not None

            event_fact = await session.scalar(select(EventFact))
            assert event_fact is not None

            report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=repo.id,
                window_start=gold_context["window_start"],
                window_end=gold_context["window_end"],
                model="gpt-5.1-thinking",
                human_text="# Weekly status\n\n- new documentation coverage",
                machine_summary={"status": "on_track", "events": 1},
            )
            report.coverage_records.append(ReportCoverage(event_fact_id=event_fact.id))

            session.add(report)
            await session.commit()

            gold_context["report_id"] = report.id

    asyncio.run(_run())


@when("I create a project-level report")
def when_create_project_report(gold_context: GoldContext) -> None:
    """Insert a project-scoped report with a machine summary payload."""

    async def _run() -> None:
        async with gold_context["session_factory"]() as session:
            project = ReportProject(key="wildside", name="Wildside")
            session.add(project)
            await session.flush()

            report = Report(
                scope=ReportScope.PROJECT,
                project_id=project.id,
                window_start=gold_context["window_start"],
                window_end=gold_context["window_end"],
                model="gpt-5.1-mini",
                machine_summary={"status": "at_risk", "highlights": []},
            )
            session.add(report)
            await session.commit()

            gold_context["report_id"] = report.id
            gold_context["project_id"] = project.id

    asyncio.run(_run())


@then("the Gold report records the repository scope and window")
def then_report_has_scope_and_window(gold_context: GoldContext) -> None:
    """Assert that repository scoped report persisted scope and window metadata."""

    async def _assert() -> None:
        async with gold_context["session_factory"]() as session:
            report = await session.get(Report, gold_context["report_id"])
            assert report is not None
            assert report.scope is ReportScope.REPOSITORY
            assert report.window_start == gold_context["window_start"]
            assert report.window_end == gold_context["window_end"]
            assert report.repository_id is not None
            assert report.machine_summary["events"] == 1

    asyncio.run(_assert())


@then("the Gold report coverage records the consumed events")
def then_report_coverage_records_events(gold_context: GoldContext) -> None:
    """Verify coverage rows map the report to the transformed event facts."""

    async def _assert() -> None:
        async with gold_context["session_factory"]() as session:
            coverage = await session.scalar(select(ReportCoverage))
            assert coverage is not None
            assert coverage.report_id == gold_context["report_id"]

            event_fact = await session.scalar(select(EventFact))
            assert event_fact is not None
            assert coverage.event_fact_id == event_fact.id

    asyncio.run(_assert())


@then("the repository is linked to the Gold report")
def then_repository_links_report(gold_context: GoldContext) -> None:
    """Ensure repository relationship exposes associated reports."""

    async def _assert() -> None:
        async with gold_context["session_factory"]() as session:
            repo = await session.scalar(select(Repository))
            assert repo is not None

            reports = (
                await session.scalars(
                    select(Report).where(Report.repository_id == repo.id)
                )
            ).all()
            assert len(reports) == 1
            assert reports[0].id == gold_context["report_id"]

    asyncio.run(_assert())


@then("the Gold report stores the project scope and summary")
def then_project_report_persists_scope_and_summary(gold_context: GoldContext) -> None:
    """Project-scoped reports retain machine summaries and linkage."""

    async def _assert() -> None:
        async with gold_context["session_factory"]() as session:
            report = await session.get(Report, gold_context["report_id"])
            assert report is not None
            assert report.scope is ReportScope.PROJECT
            assert report.project_id == gold_context["project_id"]
            assert report.machine_summary["status"] == "at_risk"

            project = await session.get(ReportProject, gold_context["project_id"])
            assert project is not None

            reports = (
                await session.scalars(
                    select(Report).where(Report.project_id == project.id)
                )
            ).all()
            assert reports[0] is report

    asyncio.run(_assert())
