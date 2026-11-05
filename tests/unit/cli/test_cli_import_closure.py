"""O6: importing the CLI must not load the server's packages.

Hecate allows the ``inbound_adapter`` group to import ``application``, so the
architecture check cannot express the thin-client rule. A clean subprocess can:
it imports :mod:`ghillie.cli.app`, prints the loaded module names, and this test
asserts that nothing from the catalogue, registry, estate, or SQLAlchemy stack
came along. The estate commands must themselves be loaded, otherwise the
assertion would be vacuous.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_FORBIDDEN_PREFIXES = (
    "ghillie.catalogue",
    "ghillie.registry",
    "ghillie.estate",
    "sqlalchemy",
)
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _clean_environment() -> dict[str, str]:
    """Return an environment without pytest's own variables."""
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("PYTEST_")
    }
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{_REPO_ROOT}{os.pathsep}{existing}" if existing else str(_REPO_ROOT)
    )
    return env


def test_importing_the_cli_loads_no_server_package() -> None:
    """The packaged CLI stays a thin HTTP client (TDD-CLI-THIN)."""
    script = "\n".join(
        [
            "import json",
            "import sys",
            "import ghillie.cli.app",
            "print(json.dumps(sorted(sys.modules)))",
        ]
    )

    # Fixed argv and the current interpreter; no untrusted input is executed.
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        cwd=_REPO_ROOT,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )

    loaded = set(json.loads(completed.stdout))
    assert "ghillie.cli.app" in loaded
    assert "ghillie.cli.commands.estate" in loaded, (
        "the estate commands must be imported for this test to mean anything"
    )
    leaked = sorted(
        name
        for name in loaded
        if any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in _FORBIDDEN_PREFIXES
        )
    )
    assert leaked == [], f"the CLI imported server modules: {leaked}"
