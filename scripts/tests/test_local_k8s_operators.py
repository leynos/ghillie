"""Unit tests for operator installation (CNPG and Valkey).

This module consolidates the structurally identical operator installation tests
to reduce duplication while maintaining comprehensive coverage.

"""

from __future__ import annotations

import typing as typ

import pytest
from conftest import make_subprocess_mock
from local_k8s import Config
from local_k8s.cnpg import install_cnpg_operator
from local_k8s.valkey import install_valkey_operator


class OperatorTestCase(typ.NamedTuple):
    """Test case parameters for operator installation tests."""

    name: str
    install_func: typ.Callable[[Config, dict[str, str]], None]
    repo_name: str
    repo_url: str
    release_name: str
    chart_name: str
    namespace: str


OPERATOR_TEST_CASES = [
    OperatorTestCase(
        name="cnpg",
        install_func=install_cnpg_operator,
        repo_name="cnpg",
        repo_url="https://cloudnative-pg.github.io/charts",
        release_name="cnpg",
        chart_name="cnpg/cloudnative-pg",
        namespace="cnpg-system",
    ),
    OperatorTestCase(
        name="valkey",
        install_func=install_valkey_operator,
        repo_name="valkey-operator",
        repo_url="https://hyperspike.github.io/valkey-operator",
        release_name="valkey-operator",
        chart_name="valkey-operator/valkey-operator",
        namespace="valkey-operator-system",
    ),
]


class TestOperatorInstallation:
    """Parametrized tests for operator installation.

    Tests verify that operator installation functions call helm and kubectl
    commands in the correct order with the expected arguments.
    """

    @pytest.mark.parametrize(
        "case",
        OPERATOR_TEST_CASES,
        ids=[c.name for c in OPERATOR_TEST_CASES],
    )
    def test_calls_expected_commands(
        self,
        monkeypatch: pytest.MonkeyPatch,
        test_env: dict[str, str],
        case: OperatorTestCase,
    ) -> None:
        """Should call helm and kubectl commands in correct order."""
        cfg = Config()
        calls: list[tuple[str, ...]] = []

        monkeypatch.setattr(
            "subprocess.run", make_subprocess_mock(calls, namespace_exists=False)
        )

        case.install_func(cfg, test_env)

        # Verify the expected commands were called
        # Note: create_namespace uses dry-run + apply pattern (2 calls)
        assert len(calls) == 6

        # 1. Add Helm repository
        assert calls[0] == (
            "helm",
            "repo",
            "add",
            "--force-update",
            case.repo_name,
            case.repo_url,
        )

        # 2. Update Helm repos
        assert calls[1] == ("helm", "repo", "update")

        # 3. Check namespace existence
        assert calls[2] == ("kubectl", "get", "namespace", case.namespace)

        # 4. Create namespace with dry-run
        assert calls[3][:4] == ("kubectl", "create", "namespace", case.namespace)
        assert "--dry-run=client" in calls[3]

        # 5. Apply namespace
        assert calls[4] == ("kubectl", "apply", "-f", "-")

        # 6. Install operator via Helm
        assert calls[5] == (
            "helm",
            "upgrade",
            "--install",
            case.release_name,
            case.chart_name,
            "--namespace",
            case.namespace,
            "--wait",
        )
