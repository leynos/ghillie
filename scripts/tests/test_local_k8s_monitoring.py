"""Unit tests for local_k8s monitoring operations."""

from __future__ import annotations

import typing as typ

import pytest
from local_k8s import Config
from local_k8s.deployment import print_status, tail_logs

if typ.TYPE_CHECKING:
    from cmd_mox import CmdMox


class TestPrintStatus:
    """Tests for print_status helper using cmd-mox."""

    @pytest.mark.parametrize(
        "namespace",
        ["ghillie", "custom-ns"],
    )
    def test_invokes_kubectl_get_pods(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
        namespace: str,
    ) -> None:
        """Should invoke kubectl get pods with correct namespace."""
        cfg = Config(namespace=namespace)

        cmd_mox.mock("kubectl").with_args(
            "get",
            "pods",
            f"--namespace={namespace}",
            "-o",
            "wide",
        ).returns(exit_code=0)

        print_status(cfg, test_env)


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
        cmd_mox: CmdMox,
        test_env: dict[str, str],
        namespace: str,
        # FBT001: Boolean is a pytest parametrized fixture, not a function API
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

        tail_logs(cfg, test_env, follow=follow)
