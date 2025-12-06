"""Gold layer primitives: report metadata and coverage tracking."""

from __future__ import annotations

from .storage import (
    Report,
    ReportCoverage,
    ReportProject,
    ReportScope,
    init_gold_storage,
)

__all__ = [
    "Report",
    "ReportCoverage",
    "ReportProject",
    "ReportScope",
    "init_gold_storage",
]
