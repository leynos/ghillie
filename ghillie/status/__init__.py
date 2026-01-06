"""Status model interface for LLM-backed summarization.

This package provides the abstraction layer for transforming evidence bundles
into structured status reports. The `StatusModel` protocol defines the
interface, while implementations like `MockStatusModel` provide concrete
behavior.

Public API
----------
StatusModel
    Protocol for status generation from evidence bundles.
RepositoryStatusResult
    Structured output for repository status reports.
MockStatusModel
    Deterministic mock implementation for testing.
to_machine_summary
    Helper to convert results for Report.machine_summary storage.

Examples
--------
>>> from ghillie.status import MockStatusModel, StatusModel
>>> model: StatusModel = MockStatusModel()
>>> result = await model.summarize_repository(evidence_bundle)
>>> result.status
<ReportStatus.ON_TRACK: 'on_track'>

"""

from __future__ import annotations

from ghillie.status.mock import MockStatusModel
from ghillie.status.models import RepositoryStatusResult, to_machine_summary
from ghillie.status.protocol import StatusModel

__all__ = [
    "MockStatusModel",
    "RepositoryStatusResult",
    "StatusModel",
    "to_machine_summary",
]
