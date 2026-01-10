"""Unit tests for local_k8s Valkey operations."""

from __future__ import annotations

import pytest
from local_k8s import (
    Config,
    create_valkey_instance,
    install_valkey_operator,
    read_valkey_uri,
    wait_for_valkey_ready,
)
from local_k8s.valkey import _valkey_manifest


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

    def test_uses_custom_valkey_name(self) -> None:
        """Should use custom Valkey name in manifest."""
        manifest = _valkey_manifest("custom-ns", "custom-valkey")

        assert "name: custom-valkey" in manifest
        assert "namespace: custom-ns" in manifest


class TestInstallValkeyOperator:
    """Tests for install_valkey_operator helper.

    Note: This test uses monkeypatch to mock subprocess.run since cmd-mox has
    issues verifying multiple expectations for the same executable. The test
    verifies that all expected subprocess calls are made in the correct order.
    """

    def test_calls_expected_commands(
        self, monkeypatch: pytest.MonkeyPatch, test_env: dict[str, str]
    ) -> None:
        """Should call helm and kubectl commands in correct order."""
        cfg = Config()
        calls: list[tuple[str, ...]] = []

        def mock_run(args: list[str], **_kwargs: object) -> object:
            calls.append(tuple(args))
            # Simulate namespace not existing (kubectl get returns non-zero)
            returncode = 1 if args[:3] == ["kubectl", "get", "namespace"] else 0
            return type("Result", (), {"stdout": "", "returncode": returncode})()

        monkeypatch.setattr("subprocess.run", mock_run)

        install_valkey_operator(cfg, test_env)

        # Verify the expected commands were called
        assert len(calls) == 5
        assert calls[0] == (
            "helm",
            "repo",
            "add",
            "--force-update",
            "valkey-operator",
            "https://hyperspike.github.io/valkey-operator",
        )
        assert calls[1] == ("helm", "repo", "update")
        assert calls[2] == ("kubectl", "get", "namespace", "valkey-operator-system")
        assert calls[3] == ("kubectl", "create", "namespace", "valkey-operator-system")
        assert calls[4] == (
            "helm",
            "upgrade",
            "--install",
            "valkey-operator",
            "valkey-operator/valkey-operator",
            "--namespace",
            "valkey-operator-system",
            "--wait",
        )


class TestCreateValkeyInstance:
    """Tests for create_valkey_instance helper using cmd-mox."""

    def test_applies_manifest(
        self,
        cmd_mox,  # noqa: ANN001
        test_env: dict[str, str],
    ) -> None:
        """Should apply Valkey manifest via kubectl."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args("apply", "-f", "-").returns(exit_code=0)

        create_valkey_instance(cfg, test_env)


class TestWaitForValkeyReady:
    """Tests for wait_for_valkey_ready helper using cmd-mox."""

    @pytest.mark.parametrize(
        "timeout",
        [300, 120],  # default timeout, custom timeout
    )
    def test_waits_for_pod_ready(
        self,
        cmd_mox,  # noqa: ANN001
        test_env: dict[str, str],
        timeout: int,
    ) -> None:
        """Should invoke kubectl wait with specified timeout."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args(
            "wait",
            "--for=condition=Ready",
            "pod",
            "--selector=app.kubernetes.io/name=valkey-ghillie",
            "--namespace=ghillie",
            f"--timeout={timeout}s",
        ).returns(exit_code=0)

        if timeout == 300:
            wait_for_valkey_ready(cfg, test_env)
        else:
            wait_for_valkey_ready(cfg, test_env, timeout=timeout)


class TestReadValkeyUri:
    """Tests for read_valkey_uri helper using cmd-mox."""

    def test_decodes_secret(
        self,
        cmd_mox,  # noqa: ANN001
        test_env: dict[str, str],
    ) -> None:
        """Should decode VALKEY_URL from Valkey secret."""
        cfg = Config()

        # "valkey://valkey-ghillie:6379" base64 encoded
        encoded_uri = "dmFsa2V5Oi8vdmFsa2V5LWdoaWxsaWU6NjM3OQ=="

        cmd_mox.mock("kubectl").with_args(
            "get",
            "secret",
            "valkey-ghillie",
            "--namespace=ghillie",
            "-o",
            "jsonpath={.data.uri}",
        ).returns(exit_code=0, stdout=encoded_uri)

        result = read_valkey_uri(cfg, test_env)

        assert result == "valkey://valkey-ghillie:6379"
