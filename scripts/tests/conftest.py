"""Pytest configuration for scripts tests.

Adds the scripts directory to the Python path for imports.
The cmd-mox plugin is registered globally via pyproject.toml.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import typing as typ
from pathlib import Path

import pytest

if typ.TYPE_CHECKING:
    from cyclopts import App

# Add scripts directory to path so we can import local_k8s
_scripts_dir = Path(__file__).resolve().parents[1]
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))


def load_script_app() -> App:
    """Load the app object from the local_k8s.py script.

    Since there is both a local_k8s/ package and a local_k8s.py script,
    Python's import system would prefer the package. This function loads
    the script directly using importlib.

    Returns:
        The Cyclopts App instance from local_k8s.py.

    """
    script_path = _scripts_dir / "local_k8s.py"
    spec = importlib.util.spec_from_file_location("local_k8s_script", script_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load script from {script_path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


@pytest.fixture
def script_app() -> App:
    """Fixture that provides the local_k8s.py App for testing."""
    return load_script_app()


@pytest.fixture
def test_env(tmp_path: Path) -> dict[str, str]:
    """Create a test environment with a temporary KUBECONFIG path.

    Returns a copy of the current environment with KUBECONFIG pointing to
    a temporary file, allowing cmd-mox shims to work properly during testing.

    Args:
        tmp_path: Pytest's temporary path fixture.

    Returns:
        Environment dictionary with KUBECONFIG set to a temp file.

    """
    env = dict(os.environ)
    env["KUBECONFIG"] = str(tmp_path / "kubeconfig-test.yaml")
    return env
