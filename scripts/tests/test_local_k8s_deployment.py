"""Unit tests for local_k8s deployment operations."""

from __future__ import annotations

import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path
from local_k8s import (
    Config,
    build_docker_image,
    create_app_secret,
    install_ghillie_chart,
)


class TestCreateAppSecret:
    """Tests for create_app_secret helper.

    Uses monkeypatch to mock subprocess.run since the function makes
    multiple subprocess calls that need to be verified together.
    """

    def test_creates_secret_with_urls(
        self, monkeypatch: pytest.MonkeyPatch, test_env: dict[str, str]
    ) -> None:
        """Should create secret with DATABASE_URL and VALKEY_URL."""
        cfg = Config()
        calls: list[tuple[str, ...]] = []

        def mock_run(args: list[str], **_kwargs: object) -> object:
            calls.append(tuple(args))
            return type("Result", (), {"stdout": "secret-yaml", "returncode": 0})()

        monkeypatch.setattr("subprocess.run", mock_run)

        create_app_secret(
            cfg,
            test_env,
            database_url="postgresql://user:pass@host:5432/db",
            valkey_url="valkey://valkey:6379",
        )

        # First call: generate secret YAML with dry-run
        assert len(calls) == 2
        assert calls[0][0] == "kubectl"
        assert "create" in calls[0]
        assert "secret" in calls[0]
        assert "generic" in calls[0]
        # Verify secret name from config is at the expected position (index 4)
        assert calls[0][4] == "ghillie"
        assert "--dry-run=client" in calls[0]
        assert (
            "--from-literal=DATABASE_URL=postgresql://user:pass@host:5432/db"
            in calls[0]
        )
        assert "--from-literal=VALKEY_URL=valkey://valkey:6379" in calls[0]

        # Second call: apply the generated YAML
        assert calls[1] == ("kubectl", "apply", "-f", "-")

    def test_uses_config_secret_name(
        self, monkeypatch: pytest.MonkeyPatch, test_env: dict[str, str]
    ) -> None:
        """Should use app_secret_name from config."""
        cfg = Config()
        calls: list[tuple[str, ...]] = []

        def mock_run(args: list[str], **_kwargs: object) -> object:
            calls.append(tuple(args))
            return type("Result", (), {"stdout": "yaml", "returncode": 0})()

        monkeypatch.setattr("subprocess.run", mock_run)

        create_app_secret(cfg, test_env, "db_url", "valkey_url")

        # Verify secret name from config is at the expected position (index 4)
        assert calls[0][4] == cfg.app_secret_name


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

    @pytest.mark.parametrize(
        ("namespace", "image_repo", "image_tag"),
        [
            ("ghillie", "ghillie", "local"),  # default values
            ("custom-ns", "custom-repo", "v1.0.0"),  # custom values
        ],
    )
    def test_invokes_helm_upgrade(  # noqa: PLR0913
        self,
        cmd_mox,  # noqa: ANN001
        test_env: dict[str, str],
        tmp_path: Path,
        namespace: str,
        image_repo: str,
        image_tag: str,
    ) -> None:
        """Should invoke helm upgrade --install with correct args."""
        # Create the chart and values paths that the function expects
        chart_path = tmp_path / "charts" / "ghillie"
        chart_path.mkdir(parents=True)
        (chart_path / "Chart.yaml").touch()

        values_file = tmp_path / "values_local.yaml"
        values_file.touch()

        cfg = Config(
            namespace=namespace,
            image_repo=image_repo,
            image_tag=image_tag,
            chart_path=chart_path,
            values_file=values_file,
        )

        cmd_mox.mock("helm").with_args(
            "upgrade",
            "--install",
            "ghillie",
            str(chart_path),
            "--namespace",
            namespace,
            "--values",
            str(values_file),
            "--set",
            f"image.repository={image_repo}",
            "--set",
            f"image.tag={image_tag}",
            "--wait",
        ).returns(exit_code=0)

        install_ghillie_chart(cfg, test_env)
