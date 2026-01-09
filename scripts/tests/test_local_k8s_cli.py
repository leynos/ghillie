"""Unit tests for local_k8s CLI structure."""

from __future__ import annotations

from conftest import load_script_app


class TestCliStructure:
    """Tests for CLI structure and subcommands."""

    def test_app_has_name(self) -> None:
        """App should have the correct name."""
        app = load_script_app()
        # Cyclopts returns name as a tuple
        assert app.name == ("local_k8s",)

    def test_app_has_version(self) -> None:
        """App should have a version."""
        app = load_script_app()
        assert app.version == "0.1.0"

    def test_app_has_up_command(self) -> None:
        """App should have an 'up' subcommand."""
        app = load_script_app()
        # Cyclopts command names are tuples
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("up",) in command_names

    def test_app_has_down_command(self) -> None:
        """App should have a 'down' subcommand."""
        app = load_script_app()
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("down",) in command_names

    def test_app_has_status_command(self) -> None:
        """App should have a 'status' subcommand."""
        app = load_script_app()
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("status",) in command_names

    def test_app_has_logs_command(self) -> None:
        """App should have a 'logs' subcommand."""
        app = load_script_app()
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("logs",) in command_names
