"""Pytest configuration for scripts tests.

Adds the scripts directory to the Python path for imports.
The cmd-mox plugin is registered globally via pyproject.toml.
"""

from __future__ import annotations

import importlib.util
import sys
import typing as typ
from pathlib import Path

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
