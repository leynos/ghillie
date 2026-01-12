"""Unit tests for local_k8s deployment operations."""

from __future__ import annotations

import dataclasses
import json
import typing as typ

import pytest
from local_k8s import Config
from local_k8s.deployment import (
    _HELM_INSTALL_TIMEOUT,
    build_docker_image,
    create_app_secret,
    install_ghillie_chart,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

    from cmd_mox import CmdMox
    from conftest import MockSubprocessCapture


class TestCreateAppSecret:
    """Tests for create_app_secret helper.

    Uses mock_subprocess_run fixture since the function applies
    a JSON manifest via stdin.
    """

    def test_creates_secret_with_urls(
        self, mock_subprocess_run: MockSubprocessCapture, test_env: dict[str, str]
    ) -> None:
        """Should create secret with DATABASE_URL and VALKEY_URL."""
        cfg = Config()

        create_app_secret(
            cfg,
            test_env,
            database_url="postgresql://user:pass@host:5432/db",
            valkey_url="valkey://valkey:6379",
        )

        # Single call: apply JSON manifest via stdin
        assert len(mock_subprocess_run.calls) == 1, "Expected one kubectl call"
        assert mock_subprocess_run.calls[0] == (
            "kubectl",
            "apply",
            "-f",
            "-",
        ), "Expected kubectl apply via stdin"

        # Verify the JSON manifest content
        assert len(mock_subprocess_run.inputs) == 1, "Expected one manifest input"
        manifest = json.loads(mock_subprocess_run.inputs[0])
        assert manifest["apiVersion"] == "v1", "Expected Secret apiVersion v1"
        assert manifest["kind"] == "Secret", "Expected Secret manifest kind"
        assert manifest["metadata"]["name"] == cfg.app_secret_name, (
            "Expected secret name from config"
        )
        assert manifest["metadata"]["namespace"] == cfg.namespace, (
            "Expected secret namespace from config"
        )
        assert manifest["metadata"]["labels"] == {
            "app.kubernetes.io/managed-by": "local_k8s",
            "app.kubernetes.io/name": cfg.app_name,
            "app.kubernetes.io/instance": cfg.app_name,
        }, "Expected standard Kubernetes labels"
        assert (
            manifest["stringData"]["DATABASE_URL"]
            == "postgresql://user:pass@host:5432/db"
        ), "Expected DATABASE_URL in stringData"
        assert manifest["stringData"]["VALKEY_URL"] == "valkey://valkey:6379", (
            "Expected VALKEY_URL in stringData"
        )

    def test_uses_config_secret_name(
        self, mock_subprocess_run: MockSubprocessCapture, test_env: dict[str, str]
    ) -> None:
        """Should use app_secret_name from config."""
        cfg = Config()

        create_app_secret(cfg, test_env, "db_url", "valkey_url")

        # Verify secret name from config is in the manifest
        assert len(mock_subprocess_run.inputs) == 1, "Expected one manifest input"
        manifest = json.loads(mock_subprocess_run.inputs[0])
        assert manifest["metadata"]["name"] == cfg.app_secret_name, (
            "Expected custom secret name from config"
        )


class TestBuildDockerImage:
    """Tests for build_docker_image helper using cmd-mox."""

    @pytest.mark.parametrize(
        ("image_repo", "image_tag"),
        [
            ("ghillie", "local"),
            ("custom-repo", "v1.0.0"),
        ],
    )
    def test_invokes_docker_build(
        self, cmd_mox: CmdMox, image_repo: str, image_tag: str
    ) -> None:
        """Should invoke docker build with correct repo and tag."""
        cmd_mox.mock("docker").with_args(
            "build",
            "-t",
            f"{image_repo}:{image_tag}",
            ".",
        ).returns(exit_code=0)

        build_docker_image(image_repo, image_tag)


@dataclasses.dataclass(slots=True)
class HelmChartParams:
    """Parameters for Helm chart installation tests."""

    namespace: str
    image_repo: str
    image_tag: str


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
            cfg.app_name,
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
            "--timeout",
            f"{_HELM_INSTALL_TIMEOUT}s",
        ).returns(exit_code=0)

        install_ghillie_chart(cfg, test_env)
