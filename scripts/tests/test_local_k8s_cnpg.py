"""Unit tests for local_k8s CNPG operations."""

from __future__ import annotations

import os

import pytest
from local_k8s import (
    Config,
    _cnpg_cluster_manifest,
    create_cnpg_cluster,
    install_cnpg_operator,
    read_pg_app_uri,
    wait_for_cnpg_ready,
)


def _test_env() -> dict[str, str]:
    """Create a test environment with KUBECONFIG set.

    Returns a copy of the current environment with KUBECONFIG set, which allows
    cmd-mox shims to work properly during testing.
    """
    env = dict(os.environ)
    env["KUBECONFIG"] = "/tmp/kubeconfig-test.yaml"  # noqa: S108
    return env


class TestCnpgClusterManifest:
    """Tests for CNPG cluster manifest generation."""

    def test_generates_valid_manifest(self) -> None:
        """Should generate a valid CNPG Cluster YAML manifest."""
        manifest = _cnpg_cluster_manifest("ghillie", "pg-ghillie")

        assert "apiVersion: postgresql.cnpg.io/v1" in manifest
        assert "kind: Cluster" in manifest
        assert "name: pg-ghillie" in manifest
        assert "namespace: ghillie" in manifest
        assert "instances: 1" in manifest
        assert "database: ghillie" in manifest

    def test_uses_custom_cluster_name(self) -> None:
        """Should use custom cluster name in manifest."""
        manifest = _cnpg_cluster_manifest("custom-ns", "custom-pg")

        assert "name: custom-pg" in manifest
        assert "namespace: custom-ns" in manifest


class TestInstallCnpgOperator:
    """Tests for install_cnpg_operator helper.

    Note: This test uses monkeypatch to mock subprocess.run since cmd-mox has
    issues verifying multiple expectations for the same executable. The test
    verifies that all expected subprocess calls are made in the correct order.
    """

    def test_calls_expected_commands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should call helm and kubectl commands in correct order."""
        cfg = Config()
        calls: list[tuple[str, ...]] = []

        def mock_run(args: list[str], **_kwargs) -> None:  # noqa: ANN003
            calls.append(tuple(args))
            # Simulate namespace not existing (kubectl get returns non-zero)
            returncode = 1 if args[:3] == ["kubectl", "get", "namespace"] else 0
            return type("Result", (), {"stdout": "", "returncode": returncode})()

        monkeypatch.setattr("subprocess.run", mock_run)

        install_cnpg_operator(cfg, _test_env())

        # Verify the expected commands were called
        assert len(calls) == 5
        assert calls[0] == (
            "helm",
            "repo",
            "add",
            "cnpg",
            "https://cloudnative-pg.github.io/charts",
        )
        assert calls[1] == ("helm", "repo", "update")
        assert calls[2] == ("kubectl", "get", "namespace", "cnpg-system")
        assert calls[3] == ("kubectl", "create", "namespace", "cnpg-system")
        assert calls[4] == (
            "helm",
            "upgrade",
            "--install",
            "cnpg",
            "cnpg/cloudnative-pg",
            "--namespace",
            "cnpg-system",
            "--wait",
        )


class TestCreateCnpgCluster:
    """Tests for create_cnpg_cluster helper using cmd-mox."""

    def test_applies_manifest(self, cmd_mox) -> None:  # noqa: ANN001
        """Should apply CNPG cluster manifest via kubectl."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args("apply", "-f", "-").returns(exit_code=0)

        create_cnpg_cluster(cfg, _test_env())


class TestWaitForCnpgReady:
    """Tests for wait_for_cnpg_ready helper using cmd-mox."""

    @pytest.mark.parametrize(
        "timeout",
        [600, 120],  # default timeout, custom timeout
    )
    def test_waits_for_pod_ready(self, cmd_mox, timeout: int) -> None:  # noqa: ANN001
        """Should invoke kubectl wait with specified timeout."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args(
            "wait",
            "--for=condition=Ready",
            "pod",
            "--selector=cnpg.io/cluster=pg-ghillie",
            "--namespace=ghillie",
            f"--timeout={timeout}s",
        ).returns(exit_code=0)

        if timeout == 600:
            wait_for_cnpg_ready(cfg, _test_env())
        else:
            wait_for_cnpg_ready(cfg, _test_env(), timeout=timeout)


class TestReadPgAppUri:
    """Tests for read_pg_app_uri helper using cmd-mox."""

    def test_decodes_secret(self, cmd_mox) -> None:  # noqa: ANN001
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
            "jsonpath={.data.uri}",
        ).returns(exit_code=0, stdout=encoded_uri)

        result = read_pg_app_uri(cfg, _test_env())

        assert result == "postgresql://ghillie:pass@pg-ghillie:5432/ghillie"
