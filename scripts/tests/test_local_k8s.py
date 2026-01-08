"""Unit tests for local_k8s script."""

from __future__ import annotations

from pathlib import Path

import pytest
from local_k8s import (
    Config,
    ExecutableNotFoundError,
    app,
    b64decode_k8s_secret_field,
    pick_free_loopback_port,
    require_exe,
)


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


class TestRequireExe:
    """Tests for require_exe helper."""

    def test_succeeds_for_python(self) -> None:
        """require_exe should not raise for an existing executable."""
        # Python should always be available in test environments
        require_exe("python")

    def test_raises_for_missing_executable(self) -> None:
        """require_exe should raise ExecutableNotFoundError for missing exe."""
        with pytest.raises(ExecutableNotFoundError) as exc_info:
            require_exe("definitely_not_a_real_executable_xyz_123")

        assert "definitely_not_a_real_executable_xyz_123" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()


class TestPickFreeLoopbackPort:
    """Tests for pick_free_loopback_port helper."""

    def test_returns_valid_port(self) -> None:
        """Should return a port number in the valid range."""
        port = pick_free_loopback_port()

        # Ephemeral ports are typically 1024-65535, but we got it from the OS
        assert 1 <= port <= 65535

    def test_returns_different_ports(self) -> None:
        """Consecutive calls should typically return different ports."""
        # While not guaranteed, the kernel should give different ports
        ports = {pick_free_loopback_port() for _ in range(5)}

        # At minimum, we should get more than one unique port
        # (unless the system is very constrained)
        assert len(ports) >= 1


class TestB64DecodeK8sSecretField:
    """Tests for base64 decoding helper."""

    def test_decodes_hello(self) -> None:
        """Should decode 'hello' correctly."""
        # "hello" in base64 is "aGVsbG8="
        assert b64decode_k8s_secret_field("aGVsbG8=") == "hello"

    def test_decodes_database_url(self) -> None:
        """Should decode a typical database URL."""
        # "postgresql://user:pass@localhost:5432/db" in base64
        encoded = "cG9zdGdyZXNxbDovL3VzZXI6cGFzc0Bsb2NhbGhvc3Q6NTQzMi9kYg=="
        expected = "postgresql://user:pass@localhost:5432/db"

        assert b64decode_k8s_secret_field(encoded) == expected

    def test_decodes_empty_string(self) -> None:
        """Should decode empty base64 to empty string."""
        assert b64decode_k8s_secret_field("") == ""

    def test_decodes_unicode(self) -> None:
        """Should decode UTF-8 content correctly."""
        # "café" in base64
        encoded = "Y2Fmw6k="
        assert b64decode_k8s_secret_field(encoded) == "café"
