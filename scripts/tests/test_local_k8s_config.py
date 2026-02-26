"""Unit tests for local_k8s Config dataclass."""

from __future__ import annotations

import dataclasses
import typing as typ
from pathlib import Path

import pytest
from local_k8s import Config


class TestConfig:
    """Tests for Config dataclass."""

    def test_config_defaults(self) -> None:
        """Config should have sensible defaults for local development."""
        cfg = Config()

        assert cfg.cluster_name == "ghillie-local", "cluster_name default mismatch"
        assert cfg.namespace == "ghillie", "namespace default mismatch"
        assert cfg.app_name == "ghillie", "app_name default mismatch"
        assert cfg.ingress_port is None, "ingress_port should default to None"
        assert cfg.chart_path == Path("charts/ghillie"), "chart_path default mismatch"
        assert cfg.image_repo == "ghillie", "image_repo default mismatch"
        assert cfg.image_tag == "local", "image_tag default mismatch"
        assert cfg.cnpg_release == "cnpg", "cnpg_release default mismatch"
        assert cfg.cnpg_namespace == "cnpg-system", "cnpg_namespace default mismatch"
        assert cfg.valkey_release == "valkey-operator", (
            "valkey_release default mismatch"
        )
        assert cfg.valkey_namespace == "valkey-operator-system", (
            "valkey_namespace default mismatch"
        )
        assert cfg.values_file == Path("tests/helm/fixtures/values_local.yaml"), (
            "values_file default mismatch"
        )
        assert cfg.pg_cluster_name == "pg-ghillie", "pg_cluster_name default mismatch"
        assert cfg.valkey_name == "valkey-ghillie", "valkey_name default mismatch"
        assert cfg.app_secret_name == cfg.app_name, "app_secret_name default mismatch"

    def test_config_is_frozen(self) -> None:
        """Config should be immutable."""
        cfg = Config()
        mutable_cfg = typ.cast("typ.Any", cfg)

        with pytest.raises(dataclasses.FrozenInstanceError):
            mutable_cfg.cluster_name = "other"

    def test_config_custom_values(self) -> None:
        """Config should accept custom values."""
        cfg = Config(
            cluster_name="custom-cluster",
            namespace="custom-ns",
            app_name="custom-app",
            ingress_port=8080,
        )

        assert cfg.cluster_name == "custom-cluster", "cluster_name not set to custom"
        assert cfg.namespace == "custom-ns", "namespace not set to custom"
        assert cfg.app_name == "custom-app", "app_name not set to custom"
        assert cfg.app_secret_name == cfg.app_name, (
            "app_secret_name should derive from app_name when not set explicitly"
        )
        assert cfg.ingress_port == 8080, "ingress_port not set to custom"
