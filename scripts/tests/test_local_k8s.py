"""Unit tests for local_k8s script."""

from __future__ import annotations

from pathlib import Path

import pytest
from local_k8s import Config, app


class TestConfig:
    """Tests for Config dataclass."""

    def test_config_defaults(self) -> None:
        """Config should have sensible defaults for local development."""
        cfg = Config()

        assert cfg.cluster_name == "ghillie-local"
        assert cfg.namespace == "ghillie"
        assert cfg.ingress_port is None
        assert cfg.chart_path == Path("charts/ghillie")
        assert cfg.image_repo == "ghillie"
        assert cfg.image_tag == "local"
        assert cfg.cnpg_release == "cnpg"
        assert cfg.cnpg_namespace == "cnpg-system"
        assert cfg.valkey_release == "valkey-operator"
        assert cfg.valkey_namespace == "valkey-operator-system"
        assert cfg.values_file == Path("tests/helm/fixtures/values_local.yaml")
        assert cfg.pg_cluster_name == "pg-ghillie"
        assert cfg.valkey_name == "valkey-ghillie"
        assert cfg.app_secret_name == "ghillie"  # noqa: S105

    def test_config_is_frozen(self) -> None:
        """Config should be immutable."""
        cfg = Config()

        with pytest.raises(AttributeError):
            cfg.cluster_name = "other"  # type: ignore[misc]

    def test_config_custom_values(self) -> None:
        """Config should accept custom values."""
        cfg = Config(
            cluster_name="custom-cluster",
            namespace="custom-ns",
            ingress_port=8080,
        )

        assert cfg.cluster_name == "custom-cluster"
        assert cfg.namespace == "custom-ns"
        assert cfg.ingress_port == 8080


class TestCliStructure:
    """Tests for CLI structure and subcommands."""

    def test_app_has_name(self) -> None:
        """App should have the correct name."""
        # Cyclopts returns name as a tuple
        assert app.name == ("local_k8s",)

    def test_app_has_version(self) -> None:
        """App should have a version."""
        assert app.version == "0.1.0"

    def test_app_has_up_command(self) -> None:
        """App should have an 'up' subcommand."""
        # Cyclopts command names are tuples
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("up",) in command_names

    def test_app_has_down_command(self) -> None:
        """App should have a 'down' subcommand."""
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("down",) in command_names

    def test_app_has_status_command(self) -> None:
        """App should have a 'status' subcommand."""
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("status",) in command_names

    def test_app_has_logs_command(self) -> None:
        """App should have a 'logs' subcommand."""
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("logs",) in command_names
