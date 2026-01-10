"""Unit tests for local_k8s k3d cluster operations."""

from __future__ import annotations

import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path
from local_k8s import (
    cluster_exists,
    create_k3d_cluster,
    delete_k3d_cluster,
    import_image_to_k3d,
    kubeconfig_env,
    write_kubeconfig,
)


class TestClusterExists:
    """Tests for cluster_exists helper using cmd-mox."""

    def test_returns_true_when_cluster_present(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return True when cluster is in k3d list."""
        cmd_mox.mock("k3d").with_args("cluster", "list", "-o", "json").returns(
            exit_code=0,
            stdout='[{"name": "ghillie-local", "nodes": []}]',
        )

        result = cluster_exists("ghillie-local")

        assert result is True

    def test_returns_false_when_cluster_absent(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return False when cluster is not in k3d list."""
        cmd_mox.mock("k3d").with_args("cluster", "list", "-o", "json").returns(
            exit_code=0,
            stdout="[]",
        )

        result = cluster_exists("ghillie-local")

        assert result is False

    def test_returns_false_when_different_cluster(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return False when only other clusters exist."""
        cmd_mox.mock("k3d").with_args("cluster", "list", "-o", "json").returns(
            exit_code=0,
            stdout='[{"name": "other-cluster", "nodes": []}]',
        )

        result = cluster_exists("ghillie-local")

        assert result is False


class TestCreateK3dCluster:
    """Tests for create_k3d_cluster helper using cmd-mox."""

    @pytest.mark.parametrize(
        ("cluster_name", "port", "agents"),
        [
            ("ghillie-local", 8080, 1),  # default agents
            ("test-cluster", 9090, 3),  # custom agents
        ],
    )
    def test_invokes_correct_command(
        self,
        cmd_mox,  # noqa: ANN001
        cluster_name: str,
        port: int,
        agents: int,
    ) -> None:
        """Should invoke k3d cluster create with correct args."""
        cmd_mox.mock("k3d").with_args(
            "cluster",
            "create",
            cluster_name,
            "--agents",
            str(agents),
            "--port",
            f"127.0.0.1:{port}:80@loadbalancer",
        ).returns(exit_code=0)

        create_k3d_cluster(cluster_name, port=port, agents=agents)


class TestDeleteK3dCluster:
    """Tests for delete_k3d_cluster helper using cmd-mox."""

    def test_invokes_delete_command(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke k3d cluster delete with cluster name."""
        cmd_mox.mock("k3d").with_args("cluster", "delete", "ghillie-local").returns(
            exit_code=0
        )

        delete_k3d_cluster("ghillie-local")


class TestWriteKubeconfig:
    """Tests for write_kubeconfig helper using cmd-mox."""

    def test_returns_kubeconfig_path(
        self,
        cmd_mox,  # noqa: ANN001
        tmp_path: Path,
    ) -> None:
        """Should return the path output by k3d kubeconfig write."""
        expected_path = tmp_path / "kubeconfig-ghillie-local.yaml"
        expected_path.touch()  # File must exist for validation
        cmd_mox.mock("k3d").with_args("kubeconfig", "write", "ghillie-local").returns(
            exit_code=0,
            stdout=f"{expected_path}\n",
        )

        result = write_kubeconfig("ghillie-local")

        assert result == expected_path


class TestKubeconfigEnv:
    """Tests for kubeconfig_env helper using cmd-mox."""

    def test_returns_env_with_kubeconfig(
        self,
        cmd_mox,  # noqa: ANN001
        tmp_path: Path,
    ) -> None:
        """Should return environment dict with KUBECONFIG set."""
        kubeconfig_path = tmp_path / "kubeconfig-test.yaml"
        kubeconfig_path.touch()  # File must exist for write_kubeconfig validation
        cmd_mox.mock("k3d").with_args("kubeconfig", "write", "test-cluster").returns(
            exit_code=0,
            stdout=f"{kubeconfig_path}\n",
        )

        env = kubeconfig_env("test-cluster")

        assert "KUBECONFIG" in env
        assert env["KUBECONFIG"] == str(kubeconfig_path)


class TestImportImageToK3d:
    """Tests for import_image_to_k3d helper using cmd-mox."""

    def test_invokes_k3d_import(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke k3d image import with correct args."""
        cmd_mox.mock("k3d").with_args(
            "image",
            "import",
            "ghillie:local",
            "--cluster",
            "ghillie-local",
        ).returns(exit_code=0)

        import_image_to_k3d("ghillie-local", "ghillie", "local")

    def test_uses_custom_cluster_name(self, cmd_mox) -> None:  # noqa: ANN001
        """Should use custom cluster name."""
        cmd_mox.mock("k3d").with_args(
            "image",
            "import",
            "myimage:v2",
            "--cluster",
            "custom-cluster",
        ).returns(exit_code=0)

        import_image_to_k3d("custom-cluster", "myimage", "v2")
