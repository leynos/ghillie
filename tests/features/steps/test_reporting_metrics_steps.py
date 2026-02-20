"""Behavioural coverage for reporting metrics and costs."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ

from pytest_bdd import given, scenario, then, when
from sqlalchemy import select

from ghillie.bronze import RawEventWriter
from ghillie.evidence import EvidenceBundleService
from ghillie.evidence.models import ReportStatus, RepositoryEvidenceBundle
from ghillie.gold import Report
from ghillie.reporting import (
    ReportingConfig,
    ReportingService,
    ReportingServiceDependencies,
)
from ghillie.reporting.metrics_service import (
    ReportingMetricsService,
    ReportingMetricsSnapshot,
)
from ghillie.silver import RawEventTransformer, Repository
from ghillie.status.metrics import ModelInvocationMetrics
from ghillie.status.models import RepositoryStatusResult
from tests.helpers.event_builders import commit_envelope

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _MetricsStatusModel:
    """Deterministic status model that emits non-zero token metrics."""

    def __init__(self) -> None:
        self.last_invocation_metrics: ModelInvocationMetrics | None = None

    async def summarize_repository(
        self,
        evidence: RepositoryEvidenceBundle,
    ) -> RepositoryStatusResult:
        await asyncio.sleep(0.005)
        self.last_invocation_metrics = ModelInvocationMetrics(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
        )
        return RepositoryStatusResult(
            summary=f"{evidence.repository.slug} remains on track.",
            status=ReportStatus.ON_TRACK,
            highlights=("Delivered planned work",),
        )


def _build_reporting_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> ReportingService:
    deps = ReportingServiceDependencies(
        session_factory=session_factory,
        evidence_service=EvidenceBundleService(session_factory),
        status_model=_MetricsStatusModel(),
    )
    return ReportingService(deps, config=ReportingConfig(window_days=7))


class ReportingMetricsContext(typ.TypedDict, total=False):
    """Mutable context shared between BDD steps."""

    session_factory: async_sessionmaker[AsyncSession]
    writer: RawEventWriter
    transformer: RawEventTransformer
    service: ReportingService
    metrics_service: ReportingMetricsService
    repo_id: str
    report: Report | None
    snapshot: ReportingMetricsSnapshot
    period_start: dt.datetime
    period_end: dt.datetime


@scenario(
    "../reporting_metrics.feature",
    "Report generation captures latency and token usage",
)
def test_report_generation_captures_metrics() -> None:
    """Wrapper for report metrics capture scenario."""


@scenario(
    "../reporting_metrics.feature",
    "Operator can query aggregate reporting metrics for a period",
)
def test_operator_can_query_aggregate_metrics() -> None:
    """Wrapper for period metrics aggregation scenario."""


@given(
    "an empty store with a repository containing events for metrics",
    target_fixture="reporting_metrics_context",
)
def given_repo_with_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> ReportingMetricsContext:
    """Set up one repository with events and a metrics-enabled reporting service."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    service = _build_reporting_service(session_factory)

    context: ReportingMetricsContext = {
        "session_factory": session_factory,
        "writer": writer,
        "transformer": transformer,
        "service": service,
        "metrics_service": ReportingMetricsService(session_factory),
    }

    async def _setup() -> str:
        repo_slug = "octo/reef"
        commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)
        await writer.ingest(
            commit_envelope(repo_slug, "metrics-001", commit_time, "feat: metrics")
        )
        await transformer.process_pending()

        async with session_factory() as session:
            repo = await session.scalar(select(Repository))
            assert repo is not None, "Repository should exist after event ingestion"
            return repo.id

    context["repo_id"] = asyncio.run(_setup())
    return context


@given(
    "multiple reports have been generated in the current period",
    target_fixture="reporting_metrics_context",
)
def given_multiple_reports_in_period(
    session_factory: async_sessionmaker[AsyncSession],
) -> ReportingMetricsContext:
    """Generate multiple reports in a single period for aggregation checks."""
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    service = _build_reporting_service(session_factory)

    context: ReportingMetricsContext = {
        "session_factory": session_factory,
        "writer": writer,
        "transformer": transformer,
        "service": service,
        "metrics_service": ReportingMetricsService(session_factory),
    }

    async def _setup() -> tuple[dt.datetime, dt.datetime]:
        commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)
        await writer.ingest(
            commit_envelope("octo/reef", "metrics-101", commit_time, "feat: one")
        )
        await writer.ingest(
            commit_envelope("octo/coral", "metrics-102", commit_time, "feat: two")
        )
        await transformer.process_pending()

        async with session_factory() as session:
            repos = (await session.scalars(select(Repository))).all()
            repo_ids = [repo.id for repo in repos]

        as_of = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        for repo_id in repo_ids:
            await service.run_for_repository(repo_id, as_of=as_of)

        async with session_factory() as session:
            generated_at_values = (
                await session.scalars(select(Report.generated_at))
            ).all()
            assert generated_at_values, "Expected generated reports in metrics scenario"
            return (
                min(generated_at_values) - dt.timedelta(days=1),
                max(generated_at_values) + dt.timedelta(days=1),
            )

    period_start, period_end = asyncio.run(_setup())
    context["period_start"] = period_start
    context["period_end"] = period_end
    return context


@when("I generate a repository report for metrics tracking")
def when_generate_repository_report(
    reporting_metrics_context: ReportingMetricsContext,
) -> None:
    """Run report generation once for the prepared repository."""

    async def _run() -> Report:
        service = reporting_metrics_context["service"]
        repo_id = reporting_metrics_context["repo_id"]
        as_of = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        report = await service.run_for_repository(repo_id, as_of=as_of)
        assert report is not None, "Report should be generated"
        return report

    reporting_metrics_context["report"] = asyncio.run(_run())


@when("I query reporting metrics for the current period")
def when_query_metrics_for_period(
    reporting_metrics_context: ReportingMetricsContext,
) -> None:
    """Fetch aggregate reporting metrics for the fixed July period."""

    async def _run() -> ReportingMetricsSnapshot:
        service = reporting_metrics_context["metrics_service"]
        return await service.get_metrics_for_period(
            reporting_metrics_context["period_start"],
            reporting_metrics_context["period_end"],
        )

    reporting_metrics_context["snapshot"] = asyncio.run(_run())


@then("the generated report has model latency recorded")
def then_generated_report_has_latency(
    reporting_metrics_context: ReportingMetricsContext,
) -> None:
    """Assert model latency is persisted on the report row."""
    report = reporting_metrics_context["report"]
    assert report is not None, "Expected generated report in BDD context"
    assert report.model_latency_ms is not None, "Expected model latency to be persisted"
    assert report.model_latency_ms > 0, "Expected model latency to be positive"


@then("the generated report has token usage recorded")
def then_generated_report_has_token_usage(
    reporting_metrics_context: ReportingMetricsContext,
) -> None:
    """Assert token usage columns are populated on the report row."""
    report = reporting_metrics_context["report"]
    assert report is not None, "Expected generated report in BDD context"
    assert report.prompt_tokens == 100, "Expected prompt token usage to be persisted"
    assert report.completion_tokens == 20, (
        "Expected completion token usage to be persisted"
    )
    assert report.total_tokens == 120, "Expected total token usage to be persisted"


@then("the snapshot includes total reports generated")
def then_snapshot_has_total_reports(
    reporting_metrics_context: ReportingMetricsContext,
) -> None:
    """Assert report count appears in aggregate snapshot."""
    snapshot = reporting_metrics_context["snapshot"]
    assert snapshot.total_reports == 2, "Expected two reports in the July period"


@then("the snapshot includes average model latency")
def then_snapshot_has_average_latency(
    reporting_metrics_context: ReportingMetricsContext,
) -> None:
    """Assert latency profile fields are populated."""
    snapshot = reporting_metrics_context["snapshot"]
    assert snapshot.avg_latency_ms is not None, "Expected average latency to be present"
    assert snapshot.avg_latency_ms > 0, "Expected average latency to be positive"
    assert snapshot.p95_latency_ms is not None, "Expected p95 latency to be present"


@then("the snapshot includes total token usage")
def then_snapshot_has_total_tokens(
    reporting_metrics_context: ReportingMetricsContext,
) -> None:
    """Assert aggregate token totals are exposed to operators."""
    snapshot = reporting_metrics_context["snapshot"]
    assert snapshot.total_prompt_tokens == 200, "Expected prompt token total to match"
    assert snapshot.total_completion_tokens == 40, (
        "Expected completion token total to match"
    )
    assert snapshot.total_tokens == 240, "Expected total token usage to match"
