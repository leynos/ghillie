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
    validation_max_attempts
        Maximum number of status-model invocations attempted when report
        validation fails.  The first invocation always happens; retries
        are ``validation_max_attempts - 1``.  Default is 2 (one retry).

    """

    window_days: int = 7
    report_sink_path: Path | None = None
    validation_max_attempts: int = 2

    @staticmethod
    def _parse_positive_int(env_var: str, default: int) -> int:
        """Read a positive integer env var, falling back to a default."""
        raw = os.environ.get(env_var, "")
        if not raw.strip():
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            msg = f"{env_var} must be an integer, got: {raw!r}"
            raise ValueError(msg) from exc
        if value < 1:
            msg = f"{env_var} must be positive, got: {value}"
            raise ValueError(msg)
        return value

    @classmethod
    def from_env(cls) -> ReportingConfig:
        """Create configuration from environment variables.

        Reads the following environment variables:

        - ``GHILLIE_REPORTING_WINDOW_DAYS``: Default window size in days.
          Must be a positive integer.
        - ``GHILLIE_REPORT_SINK_PATH``: Optional filesystem path for report
          Markdown output.
        - ``GHILLIE_VALIDATION_MAX_ATTEMPTS``: Maximum number of status-model
          invocations when validation fails.  Must be a positive integer.

        Returns
        -------
        ReportingConfig
            Configuration instance with values from environment or defaults.

        Raises
        ------
        ValueError
            If GHILLIE_REPORTING_WINDOW_DAYS is not a positive integer.

        """
        window_days = cls._parse_positive_int("GHILLIE_REPORTING_WINDOW_DAYS", 7)

        report_sink_path: Path | None = None
        raw_sink_path = os.environ.get("GHILLIE_REPORT_SINK_PATH", "")
        if raw_sink_path.strip():
            report_sink_path = Path(raw_sink_path.strip())

        validation_max_attempts = cls._parse_positive_int(
            "GHILLIE_VALIDATION_MAX_ATTEMPTS", 2
        )

        return cls(
            window_days=window_days,
            report_sink_path=report_sink_path,
            validation_max_attempts=validation_max_attempts,
        )
