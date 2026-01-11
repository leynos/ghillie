"""Unit tests for local_k8s Valkey operations.

Note: Operator installation tests are in test_local_k8s_operators.py.

"""

from __future__ import annotations

import typing as typ

import pytest
from local_k8s import Config
from local_k8s.valkey import (
    _valkey_manifest,
    create_valkey_instance,
    read_valkey_uri,
    wait_for_valkey_ready,
)

if typ.TYPE_CHECKING:
    from cmd_mox import CmdMox


class TestValkeyManifest:
    """Tests for Valkey manifest generation."""

    def test_generates_valid_manifest(self) -> None:
        """Should generate a valid Valkey CR YAML manifest."""
        manifest = _valkey_manifest("ghillie", "valkey-ghillie")

        assert "apiVersion: valkey.io/v1alpha1" in manifest
        assert "kind: Valkey" in manifest
        assert "name: valkey-ghillie" in manifest
        assert "namespace: ghillie" in manifest
        assert "replicas: 1" in manifest
        # Verify standard Kubernetes labels
        assert "app.kubernetes.io/managed-by: local_k8s" in manifest
        assert "app.kubernetes.io/name: valkey" in manifest
        assert "app.kubernetes.io/instance: valkey-ghillie" in manifest
        assert "app.kubernetes.io/component: cache" in manifest

    def test_uses_custom_valkey_name(self) -> None:
        """Should use custom Valkey name in manifest."""
        manifest = _valkey_manifest("custom-ns", "custom-valkey")

        assert "name: custom-valkey" in manifest
        assert "namespace: custom-ns" in manifest


class TestCreateValkeyInstance:
    """Tests for create_valkey_instance helper using cmd-mox."""

    def test_applies_manifest(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
    ) -> None:
        """Should apply Valkey manifest via kubectl."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args("apply", "-f", "-").returns(exit_code=0)

        create_valkey_instance(cfg, test_env)


class TestWaitForValkeyReady:
    """Tests for wait_for_valkey_ready helper using cmd-mox."""

    @pytest.mark.parametrize(
        ("expected_timeout", "call_kwargs"),
        [
            (300, {}),  # default timeout
            (120, {"timeout": 120}),  # custom timeout
        ],
    )
    def test_waits_for_pod_ready(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
        expected_timeout: int,
        call_kwargs: dict[str, int],
    ) -> None:
        """Should invoke kubectl wait with specified timeout."""
        cfg = Config()

        # Selector uses app.kubernetes.io/instance to match valkey_name in manifest
        cmd_mox.mock("kubectl").with_args(
            "wait",
            "--for=condition=Ready",
            "pod",
            "--selector=app.kubernetes.io/instance=valkey-ghillie",
            "--namespace=ghillie",
            f"--timeout={expected_timeout}s",
        ).returns(exit_code=0)

        wait_for_valkey_ready(cfg, test_env, **call_kwargs)


class TestReadValkeyUri:
    """Tests for read_valkey_uri helper using cmd-mox."""

    def test_constructs_uri_from_password(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
    ) -> None:
        """Should construct Valkey URI from password secret field."""
        cfg = Config()

        # "secretpass" base64 encoded
        # S105: This is test fixture data, not a production secret
        encoded_password = "c2VjcmV0cGFzcw=="  # noqa: S105

        # The operator only stores "password" field, not a complete URI
        cmd_mox.mock("kubectl").with_args(
            "get",
            "secret",
            "valkey-ghillie",
            "--namespace=ghillie",
            "-o",
            "jsonpath={.data['password']}",
        ).returns(exit_code=0, stdout=encoded_password)

        result = read_valkey_uri(cfg, test_env)

        # URI is constructed from password + service DNS name
        expected = "valkey://:secretpass@valkey-ghillie.ghillie.svc.cluster.local:6379"
        assert result == expected, f"Expected {expected}, got {result}"
