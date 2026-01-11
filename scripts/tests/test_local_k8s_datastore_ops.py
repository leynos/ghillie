"""Consolidated tests for CNPG and Valkey datastore operations.

This module provides parametrized tests covering common patterns across both
CNPG (PostgreSQL) and Valkey (Redis-compatible) operators:
- Manifest generation with custom names
- Resource creation via kubectl apply
- Readiness waiting with configurable timeouts

Operator-specific tests (URI reading, detailed manifest assertions) remain
in their dedicated test modules.
"""

from __future__ import annotations

import typing as typ

import pytest
from local_k8s import Config
from local_k8s.cnpg import (
    _cnpg_cluster_manifest,
    create_cnpg_cluster,
    wait_for_cnpg_ready,
)
from local_k8s.valkey import (
    _valkey_manifest,
    create_valkey_instance,
    wait_for_valkey_ready,
)

if typ.TYPE_CHECKING:
    from cmd_mox import CmdMox


class DatastoreParams(typ.NamedTuple):
    """Parameters for datastore operator tests."""

    name: str
    manifest_fn: typ.Callable[[str, str], str]
    create_fn: typ.Callable[[Config, dict[str, str]], None]
    wait_fn: typ.Callable[..., None]
    default_timeout: int
    selector: str
    instance_name: str
    custom_instance_name: str


class WaitTestCase(typ.NamedTuple):
    """Test case parameters for wait-for-ready tests."""

    params: DatastoreParams
    expected_timeout: int
    call_kwargs: dict[str, int]


CNPG_PARAMS = DatastoreParams(
    name="cnpg",
    manifest_fn=_cnpg_cluster_manifest,
    create_fn=create_cnpg_cluster,
    wait_fn=wait_for_cnpg_ready,
    default_timeout=600,
    selector="cnpg.io/cluster=pg-ghillie",
    instance_name="pg-ghillie",
    custom_instance_name="custom-pg",
)

VALKEY_PARAMS = DatastoreParams(
    name="valkey",
    manifest_fn=_valkey_manifest,
    create_fn=create_valkey_instance,
    wait_fn=wait_for_valkey_ready,
    default_timeout=300,
    selector="app.kubernetes.io/instance=valkey-ghillie",
    instance_name="valkey-ghillie",
    custom_instance_name="custom-valkey",
)


class TestManifestCustomNames:
    """Tests for manifest generation with custom names."""

    @pytest.mark.parametrize(
        "params",
        [CNPG_PARAMS, VALKEY_PARAMS],
        ids=["cnpg", "valkey"],
    )
    def test_uses_custom_names(self, params: DatastoreParams) -> None:
        """Should use custom namespace and instance name in manifest."""
        manifest = params.manifest_fn("custom-ns", params.custom_instance_name)

        assert f"name: {params.custom_instance_name}" in manifest
        assert "namespace: custom-ns" in manifest


class TestCreateResource:
    """Tests for resource creation via kubectl apply."""

    @pytest.mark.parametrize(
        "params",
        [CNPG_PARAMS, VALKEY_PARAMS],
        ids=["cnpg", "valkey"],
    )
    def test_applies_manifest(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
        params: DatastoreParams,
    ) -> None:
        """Should apply manifest via kubectl."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args("apply", "-f", "-").returns(exit_code=0)

        params.create_fn(cfg, test_env)


class TestWaitForReady:
    """Tests for readiness waiting with configurable timeouts."""

    @pytest.mark.parametrize(
        "test_case",
        [
            WaitTestCase(CNPG_PARAMS, 600, {}),
            WaitTestCase(CNPG_PARAMS, 120, {"timeout": 120}),
            WaitTestCase(VALKEY_PARAMS, 300, {}),
            WaitTestCase(VALKEY_PARAMS, 120, {"timeout": 120}),
        ],
        ids=[
            "cnpg-default",
            "cnpg-custom",
            "valkey-default",
            "valkey-custom",
        ],
    )
    def test_waits_for_pod_ready(
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
        test_case: WaitTestCase,
    ) -> None:
        """Should invoke kubectl wait with specified timeout."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args(
            "wait",
            "--for=condition=Ready",
            "pod",
            f"--selector={test_case.params.selector}",
            "--namespace=ghillie",
            f"--timeout={test_case.expected_timeout}s",
        ).returns(exit_code=0)

        test_case.params.wait_fn(cfg, test_env, **test_case.call_kwargs)
