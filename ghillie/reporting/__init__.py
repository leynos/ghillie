"""Reporting scheduler and workflow for repository status reports.

This module provides the scheduled reporting workflow that orchestrates
evidence bundle construction, status model invocation, and report persistence
in the Gold layer.

Public API
----------
ReportingConfig
    Configuration for reporting window computation and scheduling.
ReportingService
    Service that orchestrates report generation workflow.
ReportingWindow
    Dataclass representing a time window for reporting.

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
from ghillie.reporting.service import ReportingService, ReportingWindow

__all__ = [
    "ReportingConfig",
    "ReportingService",
    "ReportingWindow",
    "generate_report_job",
    "generate_reports_for_estate_job",
]
