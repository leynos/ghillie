"""Unit tests for local_k8s CNPG operations.

Note: Operator installation tests are in test_local_k8s_operators.py.
Common create/wait patterns are in test_local_k8s_datastore_ops.py.
"""

from __future__ import annotations

import typing as typ

from local_k8s import Config
from local_k8s.cnpg import _cnpg_cluster_manifest, read_pg_app_uri

if typ.TYPE_CHECKING:
    from cmd_mox import CmdMox


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
        # Verify standard Kubernetes labels
        assert "app.kubernetes.io/managed-by: local_k8s" in manifest
        assert "app.kubernetes.io/name: cnpg-cluster" in manifest
        assert "app.kubernetes.io/instance: pg-ghillie" in manifest
        assert "app.kubernetes.io/component: database" in manifest


class TestReadPgAppUri:
    """Tests for read_pg_app_uri helper using cmd-mox."""

    def test_decodes_secret(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
    ) -> None:
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
            "jsonpath={.data['uri']}",
        ).returns(exit_code=0, stdout=encoded_uri)

        result = read_pg_app_uri(cfg, test_env)

        assert result == "postgresql://ghillie:pass@pg-ghillie:5432/ghillie"
