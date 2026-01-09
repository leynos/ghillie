"""Unit tests for local_k8s deployment operations."""

from __future__ import annotations

import os
import typing as typ

if typ.TYPE_CHECKING:
    import pytest

from local_k8s import (
    Config,
    build_docker_image,
    create_app_secret,
    install_ghillie_chart,
)


def _test_env() -> dict[str, str]:
    """Create a test environment with KUBECONFIG set.

    Returns a copy of the current environment with KUBECONFIG set, which allows
    cmd-mox shims to work properly during testing.
    """
    env = dict(os.environ)
    env["KUBECONFIG"] = "/tmp/kubeconfig-test.yaml"  # noqa: S108
    return env


class TestCreateAppSecret:
    """Tests for create_app_secret helper.

    Uses monkeypatch to mock subprocess.run since the function makes
    multiple subprocess calls that need to be verified together.
    """

    def test_creates_secret_with_urls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should create secret with DATABASE_URL and VALKEY_URL."""
        cfg = Config()
        calls: list[tuple[str, ...]] = []

        def mock_run(args: list[str], **_kwargs) -> None:  # noqa: ANN003
            calls.append(tuple(args))
            return type("Result", (), {"stdout": "secret-yaml", "returncode": 0})()

        monkeypatch.setattr("subprocess.run", mock_run)

        create_app_secret(
            cfg,
            _test_env(),
            database_url="postgresql://user:pass@host:5432/db",
            valkey_url="valkey://valkey:6379",
        )

        # First call: generate secret YAML with dry-run
        assert len(calls) == 2
        assert calls[0][0] == "kubectl"
        assert "create" in calls[0]
        assert "secret" in calls[0]
        assert "generic" in calls[0]
        assert "ghillie" in calls[0]  # secret name
        assert "--dry-run=client" in calls[0]
        assert (
            "--from-literal=DATABASE_URL=postgresql://user:pass@host:5432/db"
            in calls[0]
        )
        assert "--from-literal=VALKEY_URL=valkey://valkey:6379" in calls[0]

        # Second call: apply the generated YAML
        assert calls[1] == ("kubectl", "apply", "-f", "-")

    def test_uses_config_secret_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should use app_secret_name from config."""
        cfg = Config()
        calls: list[tuple[str, ...]] = []

        def mock_run(args: list[str], **_kwargs) -> None:  # noqa: ANN003
            calls.append(tuple(args))
            return type("Result", (), {"stdout": "yaml", "returncode": 0})()

        monkeypatch.setattr("subprocess.run", mock_run)

        create_app_secret(cfg, _test_env(), "db_url", "valkey_url")

        # Verify secret name from config is used
        assert cfg.app_secret_name in calls[0]


class TestBuildDockerImage:
    """Tests for build_docker_image helper using cmd-mox."""

    def test_invokes_docker_build(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke docker build with correct tag."""
        cmd_mox.mock("docker").with_args(
            "build",
            "-t",
            "ghillie:local",
            ".",
        ).returns(exit_code=0)

        build_docker_image("ghillie", "local")

    def test_uses_custom_repo_and_tag(self, cmd_mox) -> None:  # noqa: ANN001
        """Should use custom repository and tag."""
        cmd_mox.mock("docker").with_args(
            "build",
            "-t",
            "custom-repo:v1.0.0",
            ".",
        ).returns(exit_code=0)

        build_docker_image("custom-repo", "v1.0.0")


class TestInstallGhillieChart:
    """Tests for install_ghillie_chart helper using cmd-mox."""

    def test_invokes_helm_upgrade(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke helm upgrade --install with correct args."""
        cfg = Config()

        cmd_mox.mock("helm").with_args(
            "upgrade",
            "--install",
            "ghillie",
            "charts/ghillie",
            "--namespace",
            "ghillie",
            "--values",
            "tests/helm/fixtures/values_local.yaml",
            "--set",
            "image.repository=ghillie",
            "--set",
            "image.tag=local",
            "--wait",
        ).returns(exit_code=0)

        install_ghillie_chart(cfg, _test_env())

    def test_uses_config_values(self, cmd_mox) -> None:  # noqa: ANN001
        """Should use values from config."""
        cfg = Config(
            namespace="custom-ns",
            image_repo="custom-repo",
            image_tag="v1.0.0",
        )

        cmd_mox.mock("helm").with_args(
            "upgrade",
            "--install",
            "ghillie",
            "charts/ghillie",
            "--namespace",
            "custom-ns",
            "--values",
            "tests/helm/fixtures/values_local.yaml",
            "--set",
            "image.repository=custom-repo",
            "--set",
            "image.tag=v1.0.0",
            "--wait",
        ).returns(exit_code=0)

        install_ghillie_chart(cfg, _test_env())
