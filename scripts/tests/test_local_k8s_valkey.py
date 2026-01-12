"""Unit tests for local_k8s Valkey operations.

Note: Operator installation tests are in test_local_k8s_operators.py.
Common create/wait patterns are in test_local_k8s_datastore_ops.py.
"""

from __future__ import annotations

import typing as typ

from local_k8s import Config
from local_k8s.valkey import _valkey_manifest, read_valkey_uri

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
