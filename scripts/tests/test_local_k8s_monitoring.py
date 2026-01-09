"""Unit tests for local_k8s monitoring operations."""

from __future__ import annotations

import os

from local_k8s import (
    Config,
    print_status,
    tail_logs,
)


def _test_env() -> dict[str, str]:
    """Create a test environment with KUBECONFIG set.

    Returns a copy of the current environment with KUBECONFIG set, which allows
    cmd-mox shims to work properly during testing.
    """
    env = dict(os.environ)
    env["KUBECONFIG"] = "/tmp/kubeconfig-test.yaml"  # noqa: S108
    return env


class TestPrintStatus:
    """Tests for print_status helper using cmd-mox."""

    def test_invokes_kubectl_get_pods(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke kubectl get pods with namespace."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args(
            "get",
            "pods",
            "--namespace=ghillie",
            "-o",
            "wide",
        ).returns(exit_code=0)

        print_status(cfg, _test_env())

    def test_uses_config_namespace(self, cmd_mox) -> None:  # noqa: ANN001
        """Should use namespace from config."""
        cfg = Config(namespace="custom-ns")

        cmd_mox.mock("kubectl").with_args(
            "get",
            "pods",
            "--namespace=custom-ns",
            "-o",
            "wide",
        ).returns(exit_code=0)

        print_status(cfg, _test_env())


class TestTailLogs:
    """Tests for tail_logs helper using cmd-mox."""

    def test_invokes_kubectl_logs(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke kubectl logs with selector."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args(
            "logs",
            "--selector=app.kubernetes.io/name=ghillie",
            "--namespace=ghillie",
        ).returns(exit_code=0)

        tail_logs(cfg, _test_env())

    def test_adds_follow_flag(self, cmd_mox) -> None:  # noqa: ANN001
        """Should add --follow flag when requested."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args(
            "logs",
            "--selector=app.kubernetes.io/name=ghillie",
            "--namespace=ghillie",
            "--follow",
        ).returns(exit_code=0)

        tail_logs(cfg, _test_env(), follow=True)

    def test_uses_config_namespace(self, cmd_mox) -> None:  # noqa: ANN001
        """Should use namespace from config."""
        cfg = Config(namespace="custom-ns")

        cmd_mox.mock("kubectl").with_args(
            "logs",
            "--selector=app.kubernetes.io/name=ghillie",
            "--namespace=custom-ns",
        ).returns(exit_code=0)

        tail_logs(cfg, _test_env())
