"""Reporting scheduler and workflow for repository status reports.

This module provides the scheduled reporting workflow that orchestrates
evidence bundle construction, status model invocation, and report persistence
in the Gold layer.

Public API
----------
FilesystemReportSink
    Filesystem adapter for the ``ReportSink`` protocol.
ReportSink
    Protocol (port) for writing rendered Markdown reports to storage.
ReportingConfig
    Configuration for reporting window computation and scheduling.
ReportingService
    Service that orchestrates report generation workflow.
ReportingWindow
    Dataclass representing a time window for reporting.
render_report_markdown
    Pure function to render a ``Report`` as a Markdown document.

Example:
Generate a report for a repository:

>>> from ghillie.evidence import EvidenceBundleService
>>> from ghillie.reporting import ReportingConfig, ReportingService
>>> from ghillie.status import MockStatusModel
>>>
>>> service = ReportingService(
...     session_factory=session_factory,
...     evidence_service=EvidenceBundleService(session_factory),
...     status_model=MockStatusModel(),
...     config=ReportingConfig(),
... )
>>> report = await service.run_for_repository(repository_id)

"""

from ghillie.reporting.actor import (
    generate_report_job,
    generate_reports_for_estate_job,
)
from ghillie.reporting.config import ReportingConfig
from ghillie.reporting.filesystem_sink import FilesystemReportSink
from ghillie.reporting.markdown import render_report_markdown
from ghillie.reporting.service import ReportingService, ReportingWindow
from ghillie.reporting.sink import ReportSink

__all__ = [
    "FilesystemReportSink",
    "ReportSink",
    "ReportingConfig",
    "ReportingService",
    "ReportingWindow",
    "generate_report_job",
    "generate_reports_for_estate_job",
    "render_report_markdown",
]
