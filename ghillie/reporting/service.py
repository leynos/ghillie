"""Reporting service for generating repository status reports.

This module provides the ReportingService class which orchestrates the
reporting workflow: computing reporting windows, building evidence bundles,
invoking status models, and persisting reports with coverage records.

Usage
-----
Create a service and generate a report:

>>> from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
>>> from ghillie.evidence import EvidenceBundleService
>>> from ghillie.status import MockStatusModel
>>> from ghillie.reporting import ReportingConfig, ReportingService
>>>
>>> engine = create_async_engine("sqlite+aiosqlite:///ghillie.db")
>>> session_factory = async_sessionmaker(engine, expire_on_commit=False)
>>> service = ReportingService(
...     session_factory=session_factory,
...     evidence_service=EvidenceBundleService(session_factory),
...     status_model=MockStatusModel(),
...     config=ReportingConfig(),
... )
>>> report = await service.run_for_repository(repository_id, as_of=now)

"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import typing as typ

from sqlalchemy import select

from ghillie.common.time import utcnow
from ghillie.gold.storage import Report, ReportCoverage, ReportScope
from ghillie.status.models import to_machine_summary

from .config import ReportingConfig

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.evidence.models import RepositoryEvidenceBundle
    from ghillie.evidence.service import EvidenceBundleService
    from ghillie.status.protocol import StatusModel


@dc.dataclass(frozen=True, slots=True)
class ReportingWindow:
    """Time window for a repository report.

    Attributes
    ----------
    start
        Start of the window (inclusive).
    end
        End of the window (exclusive).

    """

    start: dt.datetime
    end: dt.datetime


class ReportingService:
    """Orchestrates repository status report generation.

    This service coordinates the full reporting workflow:

    1. Compute the next reporting window based on previous reports
    2. Build an evidence bundle from Silver layer data
    3. Invoke the status model to generate summaries
    4. Persist the report and coverage records to the Gold layer

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service: EvidenceBundleService,
        status_model: StatusModel,
        config: ReportingConfig | None = None,
    ) -> None:
        """Configure the service with dependencies.

        Parameters
        ----------
        session_factory
            Async session factory for database access.
        evidence_service
            Service for building evidence bundles.
        status_model
            Model for generating status summaries.
        config
            Optional reporting configuration; uses defaults if not provided.

        """
        self._session_factory = session_factory
        self._evidence_service = evidence_service
        self._status_model = status_model
        self._config = config or ReportingConfig()

    async def compute_next_window(
        self,
        repository_id: str,
        as_of: dt.datetime | None = None,
    ) -> ReportingWindow:
        """Compute the next reporting window for a repository.

        The window starts where the previous report ended (if any), or
        `config.window_days` before `as_of` when no prior report exists.
        The window ends at `as_of`.

        Parameters
        ----------
        repository_id
            The Silver layer repository ID.
        as_of
            Reference time for window computation; defaults to now.

        Returns
        -------
        ReportingWindow
            Computed window with start and end timestamps.

        """
        window_end = as_of or utcnow()

        async with self._session_factory() as session:
            last_report = await self._fetch_last_report(session, repository_id)

        if last_report is not None:
            # Guard against as_of predating the last report's end to avoid
            # inverted windows (start > end)
            window_start = min(window_end, last_report.window_end)
        else:
            window_start = window_end - dt.timedelta(days=self._config.window_days)

        return ReportingWindow(start=window_start, end=window_end)

    async def _fetch_last_report(
        self,
        session: AsyncSession,
        repository_id: str,
    ) -> Report | None:
        """Fetch the most recent repository report."""
        stmt = (
            select(Report)
            .where(
                Report.scope == ReportScope.REPOSITORY,
                Report.repository_id == repository_id,
            )
            .order_by(Report.window_end.desc())
            .limit(1)
        )
        return await session.scalar(stmt)

    async def generate_report(
        self,
        repository_id: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
        *,
        bundle: RepositoryEvidenceBundle | None = None,
    ) -> Report:
        """Generate a repository report for the given window.

        Builds an evidence bundle (unless provided), invokes the status model,
        and persists the report with coverage records.

        Parameters
        ----------
        repository_id
            The Silver layer repository ID.
        window_start
            Start of the reporting window (inclusive).
        window_end
            End of the reporting window (exclusive).
        bundle
            Optional pre-built evidence bundle. If not provided, one will be
            built from the evidence service.

        Returns
        -------
        Report
            The persisted report record.

        Raises
        ------
        ValueError
            If window_end is not after window_start.

        """
        if window_end <= window_start:
            msg = (
                f"window_end must be after window_start, got "
                f"start={window_start.isoformat()}, end={window_end.isoformat()}"
            )
            raise ValueError(msg)

        if bundle is None:
            bundle = await self._evidence_service.build_bundle(
                repository_id=repository_id,
                window_start=window_start,
                window_end=window_end,
            )

        status_result = await self._status_model.summarize_repository(bundle)
        machine_summary = to_machine_summary(status_result)

        async with self._session_factory() as session, session.begin():
            report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=repository_id,
                window_start=window_start,
                window_end=window_end,
                model=self._get_model_identifier(),
                human_text=status_result.summary,
                machine_summary=machine_summary,
            )
            session.add(report)
            await session.flush()

            self._create_coverage_records(session, report, bundle)

            report_id = report.id

        # Fetch the persisted report to return
        async with self._session_factory() as session:
            persisted = await session.get(Report, report_id)
            if persisted is None:  # pragma: no cover - defensive check
                msg = f"Report {report_id} not found after commit"
                raise RuntimeError(msg)
            return persisted

    def _get_model_identifier(self) -> str:
        """Return the model identifier for report metadata."""
        # Check for model_id attribute on the status model
        model_id = getattr(self._status_model, "model_id", None)
        if model_id is not None:
            return str(model_id)
        # Fall back to class-based identification
        model_class = type(self._status_model).__name__
        if model_class == "MockStatusModel":
            return "mock-v1"
        return model_class.lower()

    def _create_coverage_records(
        self,
        session: AsyncSession,
        report: Report,
        bundle: RepositoryEvidenceBundle,
    ) -> None:
        """Create ReportCoverage records linking events to the report."""
        for event_fact_id in bundle.event_fact_ids:
            coverage = ReportCoverage(
                report_id=report.id,
                event_fact_id=event_fact_id,
            )
            session.add(coverage)

    async def run_for_repository(
        self,
        repository_id: str,
        as_of: dt.datetime | None = None,
    ) -> Report | None:
        """Run the full reporting workflow for a repository.

        Computes the next window and generates a report. Returns None if
        there are no events in the window worth reporting.

        Parameters
        ----------
        repository_id
            The Silver layer repository ID.
        as_of
            Reference time for window computation; defaults to now.

        Returns
        -------
        Report | None
            The generated report, or None if no events exist in the window.

        """
        window = await self.compute_next_window(repository_id, as_of=as_of)

        # Build bundle to check if there are events
        bundle = await self._evidence_service.build_bundle(
            repository_id=repository_id,
            window_start=window.start,
            window_end=window.end,
        )

        if bundle.total_event_count == 0:
            return None

        # Pass the pre-built bundle to avoid rebuilding it
        return await self.generate_report(
            repository_id=repository_id,
            window_start=window.start,
            window_end=window.end,
            bundle=bundle,
        )
