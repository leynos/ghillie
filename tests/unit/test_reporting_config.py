"""Unit tests for ReportingConfig."""

from __future__ import annotations

from pathlib import Path

import pytest

from ghillie.reporting.config import ReportingConfig


class TestReportingConfig:
    """Tests for ReportingConfig dataclass."""

    def test_default_window_days(self) -> None:
        """Default window is 7 days."""
        config = ReportingConfig()
        assert config.window_days == 7, "Default window should be 7 days"

    def test_custom_window_days(self) -> None:
        """Window days can be customized."""
        config = ReportingConfig(window_days=14)
        assert config.window_days == 14, "Custom window days not applied"

    def test_config_report_sink_path_defaults_to_none(self) -> None:
        """The report_sink_path field defaults to None."""
        config = ReportingConfig()
        assert config.report_sink_path is None, (
            "report_sink_path should default to None"
        )

    @pytest.mark.parametrize(
        ("env_vars", "expected_window_days", "expected_sink_path"),
        [
            pytest.param({}, 7, None, id="defaults"),
            pytest.param(
                {"GHILLIE_REPORTING_WINDOW_DAYS": "30"}, 30, None, id="window_days"
            ),
            pytest.param(
                {"GHILLIE_REPORT_SINK_PATH": "/var/lib/ghillie/reports"},
                7,
                Path("/var/lib/ghillie/reports"),
                id="sink_path",
            ),
            pytest.param(
                {
                    "GHILLIE_REPORTING_WINDOW_DAYS": "14",
                    "GHILLIE_REPORT_SINK_PATH": "/var/lib/ghillie/output",
                },
                14,
                Path("/var/lib/ghillie/output"),
                id="both",
            ),
        ],
    )
    def test_from_env_configuration(
        self,
        monkeypatch: pytest.MonkeyPatch,
        env_vars: dict[str, str],
        expected_window_days: int,
        expected_sink_path: Path | None,
    ) -> None:
        """from_env reads environment variables correctly."""
        monkeypatch.delenv("GHILLIE_REPORTING_WINDOW_DAYS", raising=False)
        monkeypatch.delenv("GHILLIE_REPORT_SINK_PATH", raising=False)
        for key, value in env_vars.items():
            monkeypatch.setenv(key, value)

        config = ReportingConfig.from_env()

        assert config.window_days == expected_window_days, (
            f"Expected window_days={expected_window_days}, got {config.window_days}"
        )
        assert config.report_sink_path == expected_sink_path, (
            f"Expected sink_path={expected_sink_path}, got {config.report_sink_path}"
        )
