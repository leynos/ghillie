"""Unit tests for local_k8s CLI structure."""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    from cyclopts import App


class TestCliStructure:
    """Tests for CLI structure and subcommands."""

    def test_app_has_name(self, script_app: App) -> None:
        """App should have the correct name."""
        # Cyclopts returns name as a tuple
        assert script_app.name == ("local_k8s",)

    def test_app_has_version(self, script_app: App) -> None:
        """App should have a version."""
        assert script_app.version == "0.1.0"

    def test_app_has_up_command(self, script_app: App) -> None:
        """App should have an 'up' subcommand."""
        # Use Cyclopts public API - check command exists via indexing
        assert "up" in script_app

    def test_app_has_down_command(self, script_app: App) -> None:
        """App should have a 'down' subcommand."""
        assert "down" in script_app

    def test_app_has_status_command(self, script_app: App) -> None:
        """App should have a 'status' subcommand."""
        assert "status" in script_app

    def test_app_has_logs_command(self, script_app: App) -> None:
        """App should have a 'logs' subcommand."""
        assert "logs" in script_app
