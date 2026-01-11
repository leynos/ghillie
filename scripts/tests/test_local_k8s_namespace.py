"""Unit tests for local_k8s namespace operations."""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    from cmd_mox import CmdMox

from local_k8s import (
    create_namespace,
    namespace_exists,
)


class TestNamespaceExists:
    """Tests for namespace_exists helper using cmd-mox."""

    def test_returns_true_when_present(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
    ) -> None:
        """Should return True when namespace exists."""
        cmd_mox.mock("kubectl").with_args("get", "namespace", "ghillie").returns(
            exit_code=0
        )

        result = namespace_exists("ghillie", test_env)

        assert result is True

    def test_returns_false_when_absent(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
    ) -> None:
        """Should return False when namespace does not exist."""
        cmd_mox.mock("kubectl").with_args("get", "namespace", "ghillie").returns(
            exit_code=1
        )

        result = namespace_exists("ghillie", test_env)

        assert result is False


class TestCreateNamespace:
    """Tests for create_namespace helper using cmd-mox."""

    def test_invokes_kubectl(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
    ) -> None:
        """Should invoke kubectl create namespace."""
        cmd_mox.mock("kubectl").with_args("create", "namespace", "ghillie").returns(
            exit_code=0
        )

        create_namespace("ghillie", test_env)
