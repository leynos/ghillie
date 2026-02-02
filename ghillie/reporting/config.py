"""Configuration for the reporting scheduler and workflow.

This module provides the ReportingConfig dataclass which controls reporting
window computation and scheduling behaviour.

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


@dc.dataclass(frozen=True, slots=True)
class ReportingConfig:
    """Configuration for scheduled repository reporting.

    Attributes
    ----------
    window_days
        Default number of days for a reporting window when no previous report
        exists. Subsequent windows start from the previous report's window_end.
        Default is 7 days.

    """

    window_days: int = 7

    @classmethod
    def from_env(cls) -> ReportingConfig:
        """Create configuration from environment variables.

        Reads the following environment variables:

        - ``GHILLIE_REPORTING_WINDOW_DAYS``: Default window size in days.

        Returns
        -------
        ReportingConfig
            Configuration instance with values from environment or defaults.

        """
        window_days_str = os.environ.get("GHILLIE_REPORTING_WINDOW_DAYS", "")
        window_days = int(window_days_str) if window_days_str.strip() else 7

        return cls(window_days=window_days)
