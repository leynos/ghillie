"""Unit tests for local_k8s namespace operations."""

from __future__ import annotations

import os

from local_k8s import (
    create_namespace,
    namespace_exists,
)


def _test_env() -> dict[str, str]:
    """Create a test environment with KUBECONFIG set.

    Returns a copy of the current environment with KUBECONFIG set, which allows
    cmd-mox shims to work properly during testing.
    """
    env = dict(os.environ)
    env["KUBECONFIG"] = "/tmp/kubeconfig-test.yaml"  # noqa: S108
    return env


class TestNamespaceExists:
    """Tests for namespace_exists helper using cmd-mox."""

    def test_returns_true_when_present(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return True when namespace exists."""
        cmd_mox.mock("kubectl").with_args("get", "namespace", "ghillie").returns(
            exit_code=0
        )

        result = namespace_exists("ghillie", _test_env())

        assert result is True

    def test_returns_false_when_absent(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return False when namespace does not exist."""
        cmd_mox.mock("kubectl").with_args("get", "namespace", "ghillie").returns(
            exit_code=1
        )

        result = namespace_exists("ghillie", _test_env())

        assert result is False


class TestCreateNamespace:
    """Tests for create_namespace helper using cmd-mox."""

    def test_invokes_kubectl(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke kubectl create namespace."""
        cmd_mox.mock("kubectl").with_args("create", "namespace", "ghillie").returns(
            exit_code=0
        )

        create_namespace("ghillie", _test_env())
