"""Behavioural coverage for report Markdown rendering and storage."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

from pytest_bdd import given, scenario, then, when

from ghillie.bronze import RawEventWriter
from ghillie.evidence import EvidenceBundleService
from ghillie.gold import Report, ReportScope
from ghillie.reporting import (
    ReportingConfig,
    ReportingService,
    ReportingServiceDependencies,
)
from ghillie.reporting.filesystem_sink import FilesystemReportSink
from ghillie.silver import RawEventTransformer, Repository
from ghillie.status import MockStatusModel
from tests.helpers.event_builders import commit_envelope

if typ.TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _build_reporting_service(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    report_sink: FilesystemReportSink | None = None,
) -> ReportingService:
    """Build a configured ReportingService for tests.

    Parameters
    ----------
    session_factory
        Async session factory for database access.
    report_sink
        Optional filesystem sink for Markdown output.

    Returns
    -------
    ReportingService
        Configured service with EvidenceBundleService, MockStatusModel,
        and default test configuration.

    """
    deps = ReportingServiceDependencies(
        session_factory=session_factory,
        evidence_service=EvidenceBundleService(session_factory),
        status_model=MockStatusModel(),
    )
    return ReportingService(
        deps,
        config=ReportingConfig(window_days=7),
        report_sink=report_sink,
    )


class MarkdownContext(typ.TypedDict, total=False):
    """Mutable context shared between steps."""

    session_factory: async_sessionmaker[AsyncSession]
    service: ReportingService
    repo_id: str
    report: Report | None
    sink_path: Path


@scenario(
    "../report_markdown.feature",
    "Render and store a repository report as Markdown",
)
def test_render_and_store_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


@scenario(
    "../report_markdown.feature",
    "Report generation works without a sink",
)
def test_no_sink_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


async def _setup_repository_with_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Create a repository with events and return its ID.

    Ingests a commit event for ``acme/widget`` and processes it through
    the raw event transformer, returning the resulting repository ID.

    Parameters
    ----------
    session_factory
        Async session factory for database access.

    Returns
    -------
    str
        The Silver layer repository ID.

    """
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)
    await writer.ingest(
        commit_envelope("acme/widget", "abc123", commit_time, "feat: new feature")
    )
    await transformer.process_pending()

    from sqlalchemy import select

    async with session_factory() as session:
        repo = await session.scalar(select(Repository))
        assert repo is not None, "Repository should exist after event ingestion"
        return repo.id


def _build_markdown_context(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    *,
    with_sink: bool,
) -> MarkdownContext:
    """Build a MarkdownContext with or without a filesystem sink.

    Parameters
    ----------
    session_factory
        Async session factory for database access.
    tmp_path
        Temporary directory for report storage.
    with_sink
        When ``True``, create a ``FilesystemReportSink`` and inject it
        into the reporting service.

    Returns
    -------
    MarkdownContext
        Populated context with service, repo_id, and sink_path.

    """
    sink_path = tmp_path / "reports"
    sink = FilesystemReportSink(sink_path) if with_sink else None
    service = _build_reporting_service(session_factory, report_sink=sink)

    context: MarkdownContext = {
        "session_factory": session_factory,
        "service": service,
        "sink_path": sink_path,
    }

    repo_id = asyncio.run(_setup_repository_with_events(session_factory))
    context["repo_id"] = repo_id
    return context


@given(
    "a repository with events and a filesystem sink",
    target_fixture="markdown_context",
)
def given_repo_with_events_and_sink(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> MarkdownContext:
    """Set up a repository with events and a filesystem sink."""
    return _build_markdown_context(session_factory, tmp_path, with_sink=True)


@given(
    "a repository with events but no sink",
    target_fixture="markdown_context",
)
def given_repo_with_events_no_sink(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> MarkdownContext:
    """Set up a repository with events but no sink configured."""
    return _build_markdown_context(session_factory, tmp_path, with_sink=False)


@when("I generate a report with the sink")
def when_generate_with_sink(markdown_context: MarkdownContext) -> None:
    """Generate a report using the service with a sink configured."""

    async def _run() -> Report | None:
        service = markdown_context["service"]
        repo_id = markdown_context["repo_id"]
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        return await service.run_for_repository(repo_id, as_of=now)

    report = asyncio.run(_run())
    markdown_context["report"] = report


@when("I generate a report without a sink")
def when_generate_without_sink(markdown_context: MarkdownContext) -> None:
    """Generate a report using the service without a sink."""

    async def _run() -> Report | None:
        service = markdown_context["service"]
        repo_id = markdown_context["repo_id"]
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        return await service.run_for_repository(repo_id, as_of=now)

    report = asyncio.run(_run())
    markdown_context["report"] = report


@then("a latest.md file exists at the predictable path")
def then_latest_md_exists(markdown_context: MarkdownContext) -> None:
    """Assert that latest.md was created at the expected path."""
    sink_path = markdown_context["sink_path"]
    latest = sink_path / "acme" / "widget" / "latest.md"
    assert latest.is_file(), f"latest.md should exist at {latest}"


@then("the Markdown content includes the repository name")
def then_markdown_includes_repo_name(
    markdown_context: MarkdownContext,
) -> None:
    """Assert that the Markdown contains the repository name."""
    sink_path = markdown_context["sink_path"]
    latest = sink_path / "acme" / "widget" / "latest.md"
    content = latest.read_text(encoding="utf-8")
    assert "acme/widget" in content, "Markdown should contain the repository slug"


@then("the Markdown content includes the status summary")
def then_markdown_includes_status(
    markdown_context: MarkdownContext,
) -> None:
    """Assert that the Markdown contains the status summary."""
    sink_path = markdown_context["sink_path"]
    latest = sink_path / "acme" / "widget" / "latest.md"
    content = latest.read_text(encoding="utf-8")
    assert "**Status:**" in content, "Markdown should contain the status indicator"


@then("a dated report file also exists")
def then_dated_report_exists(markdown_context: MarkdownContext) -> None:
    """Assert that a dated report file was created."""
    sink_path = markdown_context["sink_path"]
    repo_dir = sink_path / "acme" / "widget"
    dated_files = [f for f in repo_dir.iterdir() if f.name != "latest.md"]
    assert len(dated_files) == 1, "Exactly one dated report file should exist"
    assert dated_files[0].name.endswith(".md"), "Dated file should have .md extension"


@then("a Gold report is created successfully")
def then_gold_report_created(markdown_context: MarkdownContext) -> None:
    """Assert that a Gold report was created in the database."""
    report = markdown_context["report"]
    assert report is not None, "Report should be created"
    assert report.scope == ReportScope.REPOSITORY, "Report scope should be REPOSITORY"


@then("no Markdown files are written")
def then_no_markdown_files(markdown_context: MarkdownContext) -> None:
    """Assert that no Markdown files were written to the sink path."""
    sink_path = markdown_context["sink_path"]
    assert not sink_path.exists(), (
        "Sink directory should not exist when no sink is configured"
    )
