"""Unit tests for local_k8s deployment operations."""

from __future__ import annotations

import dataclasses
import subprocess
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path

    from cmd_mox import CmdMox
from local_k8s import (
    Config,
    build_docker_image,
    create_app_secret,
    install_ghillie_chart,
)


class TestCreateAppSecret:
    """Tests for create_app_secret helper.

    Uses monkeypatch to mock subprocess.run since the function applies
    a JSON manifest via stdin.
    """

    def test_creates_secret_with_urls(
        self, monkeypatch: pytest.MonkeyPatch, test_env: dict[str, str]
    ) -> None:
        """Should create secret with DATABASE_URL and VALKEY_URL."""
        import json

        cfg = Config()
        calls: list[tuple[str, ...]] = []
        captured_input: list[str] = []

        def mock_run(
            args: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            calls.append(tuple(args))
            if "input" in kwargs:
                captured_input.append(str(kwargs["input"]))
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        monkeypatch.setattr("subprocess.run", mock_run)

        create_app_secret(
            cfg,
            test_env,
            database_url="postgresql://user:pass@host:5432/db",
            valkey_url="valkey://valkey:6379",
        )

        # Single call: apply JSON manifest via stdin
        assert len(calls) == 1
        assert calls[0] == ("kubectl", "apply", "-f", "-")

        # Verify the JSON manifest content
        assert len(captured_input) == 1
        manifest = json.loads(captured_input[0])
        assert manifest["kind"] == "Secret"
        assert manifest["metadata"]["name"] == "ghillie"
        assert manifest["metadata"]["namespace"] == "ghillie"
        assert (
            manifest["stringData"]["DATABASE_URL"]
            == "postgresql://user:pass@host:5432/db"
        )
        assert manifest["stringData"]["VALKEY_URL"] == "valkey://valkey:6379"

    def test_uses_config_secret_name(
        self, monkeypatch: pytest.MonkeyPatch, test_env: dict[str, str]
    ) -> None:
        """Should use app_secret_name from config."""
        import json

        cfg = Config()
        captured_input: list[str] = []

        def mock_run(
            args: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if "input" in kwargs:
                captured_input.append(str(kwargs["input"]))
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="")

        monkeypatch.setattr("subprocess.run", mock_run)

        create_app_secret(cfg, test_env, "db_url", "valkey_url")

        # Verify secret name from config is in the manifest
        assert len(captured_input) == 1
        manifest = json.loads(captured_input[0])
        assert manifest["metadata"]["name"] == cfg.app_secret_name


class TestBuildDockerImage:
    """Tests for build_docker_image helper using cmd-mox."""

    def test_invokes_docker_build(self, cmd_mox: CmdMox) -> None:
        """Should invoke docker build with correct tag."""
        cmd_mox.mock("docker").with_args(
            "build",
            "-t",
            "ghillie:local",
            ".",
        ).returns(exit_code=0)

        build_docker_image("ghillie", "local")

    def test_uses_custom_repo_and_tag(self, cmd_mox: CmdMox) -> None:
        """Should use custom repository and tag."""
        cmd_mox.mock("docker").with_args(
            "build",
            "-t",
            "custom-repo:v1.0.0",
            ".",
        ).returns(exit_code=0)

        build_docker_image("custom-repo", "v1.0.0")


@dataclasses.dataclass
class HelmChartParams:
    """Parameters for Helm chart installation tests."""

    namespace: str
    image_repo: str
    image_tag: str


@pytest.fixture
def helm_chart_params(request: pytest.FixtureRequest) -> HelmChartParams:
    """Provide Helm chart test parameters from indirect parameterisation."""
    return request.param


class TestInstallGhillieChart:
    """Tests for install_ghillie_chart helper using cmd-mox."""

    @pytest.mark.parametrize(
        "helm_chart_params",
        [
            HelmChartParams(
                namespace="ghillie", image_repo="ghillie", image_tag="local"
            ),
            HelmChartParams(
                namespace="custom-ns", image_repo="custom-repo", image_tag="v1.0.0"
            ),
        ],
        indirect=True,
    )
    def test_invokes_helm_upgrade(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
        tmp_path: Path,
        helm_chart_params: HelmChartParams,
    ) -> None:
        """Should invoke helm upgrade --install with correct args."""
        # Create the chart and values paths that the function expects
        chart_path = tmp_path / "charts" / "ghillie"
        chart_path.mkdir(parents=True)
        (chart_path / "Chart.yaml").touch()

        values_file = tmp_path / "values_local.yaml"
        values_file.touch()

        cfg = Config(
            namespace=helm_chart_params.namespace,
            image_repo=helm_chart_params.image_repo,
            image_tag=helm_chart_params.image_tag,
            chart_path=chart_path,
            values_file=values_file,
        )

        cmd_mox.mock("helm").with_args(
            "upgrade",
            "--install",
            "ghillie",
            str(chart_path),
            "--namespace",
            helm_chart_params.namespace,
            "--create-namespace",
            "--values",
            str(values_file),
            "--set",
            f"image.repository={helm_chart_params.image_repo}",
            "--set",
            f"image.tag={helm_chart_params.image_tag}",
            "--wait",
        ).returns(exit_code=0)

        install_ghillie_chart(cfg, test_env)
