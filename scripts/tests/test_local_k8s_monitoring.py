"""Unit tests for local_k8s monitoring operations."""

from __future__ import annotations

import os

import pytest
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

    @pytest.mark.parametrize(
        "namespace",
        ["ghillie", "custom-ns"],
    )
    def test_invokes_kubectl_get_pods(self, cmd_mox, namespace: str) -> None:  # noqa: ANN001
        """Should invoke kubectl get pods with correct namespace."""
        cfg = Config(namespace=namespace)

        cmd_mox.mock("kubectl").with_args(
            "get",
            "pods",
            f"--namespace={namespace}",
            "-o",
            "wide",
        ).returns(exit_code=0)

        print_status(cfg, _test_env())


class TestTailLogs:
    """Tests for tail_logs helper using cmd-mox."""

    @pytest.mark.parametrize(
        ("namespace", "follow"),
        [
            ("ghillie", False),
            ("custom-ns", False),
            ("ghillie", True),
        ],
    )
    def test_invokes_kubectl_logs(
        self,
        cmd_mox,  # noqa: ANN001
        namespace: str,
        follow: bool,  # noqa: FBT001
    ) -> None:
        """Should invoke kubectl logs with correct arguments."""
        cfg = Config(namespace=namespace)

        expected_args = [
            "logs",
            "--selector=app.kubernetes.io/name=ghillie",
            f"--namespace={namespace}",
        ]
        if follow:
            expected_args.append("--follow")

        cmd_mox.mock("kubectl").with_args(*expected_args).returns(exit_code=0)

        tail_logs(cfg, _test_env(), follow=follow)
