"""Configuration for the reporting scheduler and workflow.

This module provides the ReportingConfig dataclass which controls reporting
window computation, scheduling behaviour, and report sink configuration.

Usage
-----
Create a configuration with defaults:

>>> config = ReportingConfig()
>>> config.window_days
7

Or load from environment variables:

>>> import os
>>> os.environ["GHILLIE_REPORTING_WINDOW_DAYS"] = "14"
>>> config = ReportingConfig.from_env()
>>> config.window_days
14

"""

from __future__ import annotations

import dataclasses as dc
import os
from pathlib import Path


@dc.dataclass(frozen=True, slots=True)
class ReportingConfig:
    """Configuration for scheduled repository reporting.

    Attributes
    ----------
    window_days
        Default number of days for a reporting window when no previous report
        exists. Subsequent windows start from the previous report's window_end.
        Default is 7 days.
    report_sink_path
        Optional filesystem path for writing rendered Markdown reports. When
        set, reports are written to ``{path}/{owner}/{name}/latest.md`` and
        ``{path}/{owner}/{name}/{date}-{report_id}.md``. When ``None``, no
        Markdown files are produced.

    """

    window_days: int = 7
    report_sink_path: Path | None = None

    @classmethod
    def from_env(cls) -> ReportingConfig:
        """Create configuration from environment variables.

        Reads the following environment variables:

        - ``GHILLIE_REPORTING_WINDOW_DAYS``: Default window size in days.
          Must be a positive integer.
        - ``GHILLIE_REPORT_SINK_PATH``: Optional filesystem path for report
          Markdown output.

        Returns
        -------
        ReportingConfig
            Configuration instance with values from environment or defaults.

        Raises
        ------
        ValueError
            If GHILLIE_REPORTING_WINDOW_DAYS is not a positive integer.

        """
        window_days_str = os.environ.get("GHILLIE_REPORTING_WINDOW_DAYS", "")
        if window_days_str.strip():
            try:
                window_days = int(window_days_str)
            except ValueError as exc:
                msg = (
                    f"GHILLIE_REPORTING_WINDOW_DAYS must be an integer, "
                    f"got: {window_days_str!r}"
                )
                raise ValueError(msg) from exc
            if window_days < 1:
                msg = (
                    f"GHILLIE_REPORTING_WINDOW_DAYS must be positive, "
                    f"got: {window_days}"
                )
                raise ValueError(msg)
        else:
            window_days = 7

        report_sink_path: Path | None = None
        raw_sink_path = os.environ.get("GHILLIE_REPORT_SINK_PATH", "")
        if raw_sink_path.strip():
            report_sink_path = Path(raw_sink_path.strip())

        return cls(window_days=window_days, report_sink_path=report_sink_path)
