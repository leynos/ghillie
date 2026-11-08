"""Behaviour tests for the ``make interrogate`` docstring-coverage gate.

The tests replace the Interrogate command with a stub script, so they check
what the target does with a report and an exit status rather than the wording
of the recipe. A gap hidden by a rounded percentage, a tool that fails, and a
clean report each have their own case, and a dry run of ``make lint`` shows the
gate is a prerequisite of the lint target.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
import typing as typ
from pathlib import Path

import pytest

if typ.TYPE_CHECKING:
    import collections.abc as cabc

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKE = shutil.which("make")

pytestmark = pytest.mark.skipif(MAKE is None, reason="make is not installed")

_CLEAN_REPORT = (
    "| ghillie/app.py | COVERED |\nRESULT: PASSED (minimum: 100.0%, actual: 100.0%)\n"
)
_MISSED_REPORT = (
    "| ghillie/app.py |  MISSED |\nRESULT: PASSED (minimum: 100.0%, actual: 99.6%)\n"
)


def _stub(tmp_path: Path, report: str, exit_code: int) -> Path:
    """Write an executable stand-in that prints *report* and exits with *exit_code*."""
    report_file = tmp_path / "report.txt"
    report_file.write_text(report, encoding="utf-8")
    script = tmp_path / "interrogate-stub"
    script.write_text(
        f'#!/bin/sh\ncat "{report_file}"\nexit {exit_code}\n', encoding="utf-8"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def _run_gate(stub: Path) -> subprocess.CompletedProcess[str]:
    """Run ``make interrogate`` with the Interrogate command replaced by *stub*."""
    assert MAKE is not None  # narrowed by the module skip marker
    return subprocess.run(  # noqa: S603  # fixed arguments, no shell
        [MAKE, "-s", "-C", str(REPO_ROOT), "interrogate", f"INTERROGATE={stub}"],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def stub_factory(tmp_path: Path) -> cabc.Callable[[str, int], Path]:
    """Return a builder for stub commands that live under the test's temp path."""

    def build(report: str, exit_code: int) -> Path:
        """Build one stub command printing *report* and exiting with *exit_code*."""
        return _stub(tmp_path, report, exit_code)

    return build


def test_clean_report_passes(stub_factory: cabc.Callable[[str, int], Path]) -> None:
    """A fully documented report with a zero exit status passes the gate."""
    result = _run_gate(stub_factory(_CLEAN_REPORT, 0))

    assert result.returncode == 0, result.stderr


def test_missed_row_fails_despite_successful_exit(
    stub_factory: cabc.Callable[[str, int], Path],
) -> None:
    """A MISSED row fails the gate even when the tool itself exits zero."""
    result = _run_gate(stub_factory(_MISSED_REPORT, 0))

    assert result.returncode != 0
    assert "undocumented definitions remain" in result.stderr


def test_tool_failure_status_propagates(
    stub_factory: cabc.Callable[[str, int], Path],
) -> None:
    """A non-zero tool exit fails the gate and make reports that status."""
    result = _run_gate(stub_factory(_CLEAN_REPORT, 3))

    assert result.returncode != 0
    assert "Error 3" in result.stderr


def test_lint_runs_the_gate() -> None:
    """A dry run of ``make lint`` reaches the interrogate recipe."""
    assert MAKE is not None  # narrowed by the module skip marker
    marker = "interrogate-gate-marker"
    result = subprocess.run(  # noqa: S603  # fixed arguments, no shell
        [MAKE, "-n", "-C", str(REPO_ROOT), "lint", f"INTERROGATE={marker}"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert marker in result.stdout
