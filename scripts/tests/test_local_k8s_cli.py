"""Unit tests for local_k8s CLI structure."""

from __future__ import annotations

import importlib.util
import typing as typ
from pathlib import Path

if typ.TYPE_CHECKING:
    from cyclopts import App


def _load_script_app() -> App:
    """Load the app object from the local_k8s.py script.

    Since we have both a local_k8s/ package and a local_k8s.py script,
    Python's import system would prefer the package. This function loads
    the script directly using importlib.
    """
    script_path = Path(__file__).parent.parent / "local_k8s.py"
    spec = importlib.util.spec_from_file_location("local_k8s_script", script_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load script from {script_path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


class TestCliStructure:
    """Tests for CLI structure and subcommands."""

    def test_app_has_name(self) -> None:
        """App should have the correct name."""
        app = _load_script_app()
        # Cyclopts returns name as a tuple
        assert app.name == ("local_k8s",)

    def test_app_has_version(self) -> None:
        """App should have a version."""
        app = _load_script_app()
        assert app.version == "0.1.0"

    def test_app_has_up_command(self) -> None:
        """App should have an 'up' subcommand."""
        app = _load_script_app()
        # Cyclopts command names are tuples
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("up",) in command_names

    def test_app_has_down_command(self) -> None:
        """App should have a 'down' subcommand."""
        app = _load_script_app()
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("down",) in command_names

    def test_app_has_status_command(self) -> None:
        """App should have a 'status' subcommand."""
        app = _load_script_app()
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("status",) in command_names

    def test_app_has_logs_command(self) -> None:
        """App should have a 'logs' subcommand."""
        app = _load_script_app()
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("logs",) in command_names
