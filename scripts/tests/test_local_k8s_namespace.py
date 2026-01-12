"""Unit tests for local_k8s namespace operations."""

from __future__ import annotations

import typing as typ

from conftest import make_subprocess_mock
from local_k8s.k8s import create_namespace, namespace_exists

if typ.TYPE_CHECKING:
    import pytest
    from cmd_mox import CmdMox


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
    """Tests for create_namespace helper.

    Uses monkeypatch since the function makes multiple subprocess calls that
    need to be verified together (dry-run + apply pattern).
    """

    def test_uses_dry_run_apply_pattern(
        self, monkeypatch: pytest.MonkeyPatch, test_env: dict[str, str]
    ) -> None:
        """Should use dry-run + apply pattern for idempotent namespace creation."""
        calls: list[tuple[str, ...]] = []

        monkeypatch.setattr(
            "subprocess.run",
            make_subprocess_mock(calls, namespace_exists=True, stdout="namespace-yaml"),
        )

        create_namespace("ghillie", test_env)

        # First call: generate namespace YAML with dry-run
        assert len(calls) == 2
        assert calls[0][0] == "kubectl"
        assert "create" in calls[0]
        assert "namespace" in calls[0]
        assert "ghillie" in calls[0]
        assert "--dry-run=client" in calls[0]
        assert "-o" in calls[0]
        assert "yaml" in calls[0]

        # Second call: apply the generated YAML
        assert calls[1] == ("kubectl", "apply", "-f", "-")
