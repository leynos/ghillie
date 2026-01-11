"""Unit tests for local_k8s Config dataclass."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from local_k8s import Config


class TestConfig:
    """Tests for Config dataclass."""

    def test_config_defaults(self) -> None:
        """Config should have sensible defaults for local development."""
        cfg = Config()

        assert cfg.cluster_name == "ghillie-local"
        assert cfg.namespace == "ghillie"
        assert cfg.ingress_port is None
        assert cfg.chart_path == Path("charts/ghillie")
        assert cfg.image_repo == "ghillie"
        assert cfg.image_tag == "local"
        assert cfg.cnpg_release == "cnpg"
        assert cfg.cnpg_namespace == "cnpg-system"
        assert cfg.valkey_release == "valkey-operator"
        assert cfg.valkey_namespace == "valkey-operator-system"
        assert cfg.values_file == Path("tests/helm/fixtures/values_local.yaml")
        assert cfg.pg_cluster_name == "pg-ghillie"
        assert cfg.valkey_name == "valkey-ghillie"
        # S105 suppression: Bandit flags "ghillie" as a potential hardcoded
        # password. This is a Kubernetes Secret name, not a password value.
        assert cfg.app_secret_name == "ghillie"  # noqa: S105

    def test_config_is_frozen(self) -> None:
        """Config should be immutable."""
        cfg = Config()

        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.cluster_name = "other"  # type: ignore[misc]

    def test_config_custom_values(self) -> None:
        """Config should accept custom values."""
        cfg = Config(
            cluster_name="custom-cluster",
            namespace="custom-ns",
            ingress_port=8080,
        )

        assert cfg.cluster_name == "custom-cluster"
        assert cfg.namespace == "custom-ns"
        assert cfg.ingress_port == 8080
