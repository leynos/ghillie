"""Unit tests for local_k8s CNPG operations.

Note: Operator installation tests are in test_local_k8s_operators.py.
Common create/wait patterns are in test_local_k8s_datastore_ops.py.
"""

from __future__ import annotations

import subprocess
import typing as typ

import pytest
from local_k8s import Config, LocalK8sError
from local_k8s.cnpg import cnpg_cluster_manifest, read_pg_app_uri, wait_for_cnpg_ready

if typ.TYPE_CHECKING:
    from cmd_mox import CmdMox


class TestCnpgClusterManifest:
    """Tests for CNPG cluster manifest generation."""

    def test_generates_valid_manifest(self) -> None:
        """Should generate a valid CNPG Cluster YAML manifest."""
        manifest = cnpg_cluster_manifest("ghillie", "pg-ghillie")

        assert "apiVersion: postgresql.cnpg.io/v1" in manifest
        assert "kind: Cluster" in manifest
        assert "name: pg-ghillie" in manifest
        assert "namespace: ghillie" in manifest
        assert "instances: 1" in manifest
        assert "database: ghillie" in manifest
        # Verify standard Kubernetes labels
        assert "app.kubernetes.io/managed-by: local_k8s" in manifest
        assert "app.kubernetes.io/name: cnpg-cluster" in manifest
        assert "app.kubernetes.io/instance: pg-ghillie" in manifest
        assert "app.kubernetes.io/component: database" in manifest


class TestReadPgAppUri:
    """Tests for read_pg_app_uri helper using cmd-mox."""

    def test_decodes_secret(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
    ) -> None:
        """Should decode DATABASE_URL from CNPG app secret."""
        cfg = Config()

        # "postgresql://ghillie:pass@pg-ghillie:5432/ghillie" base64 encoded
        encoded_uri = (
            "cG9zdGdyZXNxbDovL2doaWxsaWU6cGFzc0BwZy1naGlsbGllOjU0MzIvZ2hpbGxpZQ=="
        )

        cmd_mox.mock("kubectl").with_args(
            "get",
            "secret",
            "pg-ghillie-app",
            "--namespace=ghillie",
            "-o",
            "jsonpath={.data['uri']}",
        ).returns(exit_code=0, stdout=encoded_uri)

        result = read_pg_app_uri(cfg, test_env)

        assert result == "postgresql://ghillie:pass@pg-ghillie:5432/ghillie"


class TestWaitForCnpgReadyErrors:
    """Tests for wait_for_cnpg_ready error handling.

    Uses monkeypatch rather than cmd-mox because the pre-flight check uses
    capture_output=True which requires specific subprocess result handling.
    """

    def test_raises_when_no_pods_exist(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_env: dict[str, str],
    ) -> None:
        """Should raise LocalK8sError when pre-flight check finds no pods."""
        cfg = Config()

        def mock_run(
            args: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if args[1:3] == ["get", "pods"]:
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout='{"items": []}', stderr=""
                )
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("subprocess.run", mock_run)

        with pytest.raises(LocalK8sError, match="has no pods"):
            wait_for_cnpg_ready(cfg, test_env)

    def test_raises_when_pod_check_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_env: dict[str, str],
    ) -> None:
        """Should raise LocalK8sError when kubectl get pods fails."""
        cfg = Config()

        def mock_run(
            args: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if args[1:3] == ["get", "pods"]:
                return subprocess.CompletedProcess(
                    args=args, returncode=1, stdout="", stderr="connection refused"
                )
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("subprocess.run", mock_run)

        with pytest.raises(LocalK8sError, match="has no pods"):
            wait_for_cnpg_ready(cfg, test_env)

    def test_raises_contextual_error_on_timeout(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_env: dict[str, str],
    ) -> None:
        """Should raise LocalK8sError with timeout guidance when wait times out."""
        cfg = Config()

        def mock_run(
            args: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if args[1:3] == ["get", "pods"]:
                # Pre-flight check passes
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout='{"items": [{"metadata": {"name": "pod-1"}}]}',
                    stderr="",
                )
            if args[1] == "wait":
                # Wait times out (check=True will raise CalledProcessError)
                raise subprocess.CalledProcessError(
                    1, args, "", "error: timed out waiting for condition"
                )
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("subprocess.run", mock_run)

        with pytest.raises(LocalK8sError, match="Timeout waiting"):
            wait_for_cnpg_ready(cfg, test_env)

    def test_raises_contextual_error_on_generic_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_env: dict[str, str],
    ) -> None:
        """Should raise LocalK8sError with stderr on generic kubectl failure."""
        cfg = Config()

        def mock_run(
            args: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            if args[1:3] == ["get", "pods"]:
                # Pre-flight check passes
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout='{"items": [{"metadata": {"name": "pod-1"}}]}',
                    stderr="",
                )
            if args[1] == "wait":
                # Wait fails with generic error (check=True will raise)
                raise subprocess.CalledProcessError(
                    1, args, "", "error: some other failure"
                )
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr("subprocess.run", mock_run)

        with pytest.raises(LocalK8sError, match="Failed waiting"):
            wait_for_cnpg_ready(cfg, test_env)
