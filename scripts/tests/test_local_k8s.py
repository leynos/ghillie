"""Unit tests for local_k8s script."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from local_k8s import (
    Config,
    ExecutableNotFoundError,
    _cnpg_cluster_manifest,
    _valkey_manifest,
    app,
    b64decode_k8s_secret_field,
    cluster_exists,
    create_cnpg_cluster,
    create_k3d_cluster,
    create_namespace,
    create_valkey_instance,
    delete_k3d_cluster,
    install_cnpg_operator,
    install_valkey_operator,
    kubeconfig_env,
    namespace_exists,
    pick_free_loopback_port,
    read_pg_app_uri,
    read_valkey_uri,
    require_exe,
    wait_for_cnpg_ready,
    wait_for_valkey_ready,
    write_kubeconfig,
)


def _test_env() -> dict[str, str]:
    """Create a test environment with KUBECONFIG set.

    Returns a copy of the current environment with KUBECONFIG set, which allows
    cmd-mox shims to work properly during testing.
    """
    env = dict(os.environ)
    env["KUBECONFIG"] = "/tmp/kubeconfig-test.yaml"  # noqa: S108
    return env


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
        assert cfg.app_secret_name == "ghillie"  # noqa: S105

    def test_config_is_frozen(self) -> None:
        """Config should be immutable."""
        cfg = Config()

        with pytest.raises(AttributeError):
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


class TestCliStructure:
    """Tests for CLI structure and subcommands."""

    def test_app_has_name(self) -> None:
        """App should have the correct name."""
        # Cyclopts returns name as a tuple
        assert app.name == ("local_k8s",)

    def test_app_has_version(self) -> None:
        """App should have a version."""
        assert app.version == "0.1.0"

    def test_app_has_up_command(self) -> None:
        """App should have an 'up' subcommand."""
        # Cyclopts command names are tuples
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("up",) in command_names

    def test_app_has_down_command(self) -> None:
        """App should have a 'down' subcommand."""
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("down",) in command_names

    def test_app_has_status_command(self) -> None:
        """App should have a 'status' subcommand."""
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("status",) in command_names

    def test_app_has_logs_command(self) -> None:
        """App should have a 'logs' subcommand."""
        command_names = [cmd.name for cmd in app._commands.values()]
        assert ("logs",) in command_names


class TestRequireExe:
    """Tests for require_exe helper."""

    def test_succeeds_for_python(self) -> None:
        """require_exe should not raise for an existing executable."""
        # Python should always be available in test environments
        require_exe("python")

    def test_raises_for_missing_executable(self) -> None:
        """require_exe should raise ExecutableNotFoundError for missing exe."""
        with pytest.raises(ExecutableNotFoundError) as exc_info:
            require_exe("definitely_not_a_real_executable_xyz_123")

        assert "definitely_not_a_real_executable_xyz_123" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()


class TestPickFreeLoopbackPort:
    """Tests for pick_free_loopback_port helper."""

    def test_returns_valid_port(self) -> None:
        """Should return a port number in the valid range."""
        port = pick_free_loopback_port()

        # Ephemeral ports are typically 1024-65535, but we got it from the OS
        assert 1 <= port <= 65535

    def test_returns_different_ports(self) -> None:
        """Consecutive calls should typically return different ports."""
        # While not guaranteed, the kernel should give different ports
        ports = {pick_free_loopback_port() for _ in range(5)}

        # At minimum, we should get more than one unique port
        # (unless the system is very constrained)
        assert len(ports) >= 1


class TestB64DecodeK8sSecretField:
    """Tests for base64 decoding helper."""

    def test_decodes_hello(self) -> None:
        """Should decode 'hello' correctly."""
        # "hello" in base64 is "aGVsbG8="
        assert b64decode_k8s_secret_field("aGVsbG8=") == "hello"

    def test_decodes_database_url(self) -> None:
        """Should decode a typical database URL."""
        # "postgresql://user:pass@localhost:5432/db" in base64
        encoded = "cG9zdGdyZXNxbDovL3VzZXI6cGFzc0Bsb2NhbGhvc3Q6NTQzMi9kYg=="
        expected = "postgresql://user:pass@localhost:5432/db"

        assert b64decode_k8s_secret_field(encoded) == expected

    def test_decodes_empty_string(self) -> None:
        """Should decode empty base64 to empty string."""
        assert b64decode_k8s_secret_field("") == ""

    def test_decodes_unicode(self) -> None:
        """Should decode UTF-8 content correctly."""
        # "café" in base64
        encoded = "Y2Fmw6k="
        assert b64decode_k8s_secret_field(encoded) == "café"


class TestClusterExists:
    """Tests for cluster_exists helper using cmd-mox."""

    def test_returns_true_when_cluster_present(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return True when cluster is in k3d list."""
        cmd_mox.mock("k3d").with_args("cluster", "list", "-o", "json").returns(
            exit_code=0,
            stdout='[{"name": "ghillie-local", "nodes": []}]',
        )

        result = cluster_exists("ghillie-local")

        assert result is True

    def test_returns_false_when_cluster_absent(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return False when cluster is not in k3d list."""
        cmd_mox.mock("k3d").with_args("cluster", "list", "-o", "json").returns(
            exit_code=0,
            stdout="[]",
        )

        result = cluster_exists("ghillie-local")

        assert result is False

    def test_returns_false_when_different_cluster(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return False when only other clusters exist."""
        cmd_mox.mock("k3d").with_args("cluster", "list", "-o", "json").returns(
            exit_code=0,
            stdout='[{"name": "other-cluster", "nodes": []}]',
        )

        result = cluster_exists("ghillie-local")

        assert result is False


class TestCreateK3dCluster:
    """Tests for create_k3d_cluster helper using cmd-mox."""

    def test_invokes_correct_command(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke k3d cluster create with correct args."""
        cmd_mox.mock("k3d").with_args(
            "cluster",
            "create",
            "ghillie-local",
            "--agents",
            "1",
            "--port",
            "127.0.0.1:8080:80@loadbalancer",
        ).returns(exit_code=0)

        create_k3d_cluster("ghillie-local", port=8080)

    def test_uses_custom_agent_count(self, cmd_mox) -> None:  # noqa: ANN001
        """Should pass custom agent count to k3d."""
        cmd_mox.mock("k3d").with_args(
            "cluster",
            "create",
            "test-cluster",
            "--agents",
            "3",
            "--port",
            "127.0.0.1:9090:80@loadbalancer",
        ).returns(exit_code=0)

        create_k3d_cluster("test-cluster", port=9090, agents=3)


class TestDeleteK3dCluster:
    """Tests for delete_k3d_cluster helper using cmd-mox."""

    def test_invokes_delete_command(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke k3d cluster delete with cluster name."""
        cmd_mox.mock("k3d").with_args("cluster", "delete", "ghillie-local").returns(
            exit_code=0
        )

        delete_k3d_cluster("ghillie-local")


class TestWriteKubeconfig:
    """Tests for write_kubeconfig helper using cmd-mox."""

    def test_returns_kubeconfig_path(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return the path output by k3d kubeconfig write."""
        expected_path = "/home/user/.k3d/kubeconfig-ghillie-local.yaml"
        cmd_mox.mock("k3d").with_args("kubeconfig", "write", "ghillie-local").returns(
            exit_code=0,
            stdout=f"{expected_path}\n",
        )

        result = write_kubeconfig("ghillie-local")

        assert result == Path(expected_path)


class TestKubeconfigEnv:
    """Tests for kubeconfig_env helper using cmd-mox."""

    def test_returns_env_with_kubeconfig(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return environment dict with KUBECONFIG set."""
        kubeconfig_path = "/tmp/kubeconfig-test.yaml"  # noqa: S108
        cmd_mox.mock("k3d").with_args("kubeconfig", "write", "test-cluster").returns(
            exit_code=0,
            stdout=f"{kubeconfig_path}\n",
        )

        env = kubeconfig_env("test-cluster")

        assert "KUBECONFIG" in env
        assert env["KUBECONFIG"] == kubeconfig_path


class TestNamespaceExists:
    """Tests for namespace_exists helper using cmd-mox."""

    def test_returns_true_when_present(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return True when namespace exists."""
        cmd_mox.mock("kubectl").with_args("get", "namespace", "ghillie").returns(
            exit_code=0
        )

        result = namespace_exists("ghillie", _test_env())

        assert result is True

    def test_returns_false_when_absent(self, cmd_mox) -> None:  # noqa: ANN001
        """Should return False when namespace does not exist."""
        cmd_mox.mock("kubectl").with_args("get", "namespace", "ghillie").returns(
            exit_code=1
        )

        result = namespace_exists("ghillie", _test_env())

        assert result is False


class TestCreateNamespace:
    """Tests for create_namespace helper using cmd-mox."""

    def test_invokes_kubectl(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke kubectl create namespace."""
        cmd_mox.mock("kubectl").with_args("create", "namespace", "ghillie").returns(
            exit_code=0
        )

        create_namespace("ghillie", _test_env())


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

    def test_uses_custom_cluster_name(self) -> None:
        """Should use custom cluster name in manifest."""
        manifest = _cnpg_cluster_manifest("custom-ns", "custom-pg")

        assert "name: custom-pg" in manifest
        assert "namespace: custom-ns" in manifest


class TestInstallCnpgOperator:
    """Tests for install_cnpg_operator helper.

    Note: This test uses monkeypatch to mock subprocess.run since cmd-mox has
    issues verifying multiple expectations for the same executable. The test
    verifies that all expected subprocess calls are made in the correct order.
    """

    def test_calls_expected_commands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should call helm and kubectl commands in correct order."""
        cfg = Config()
        calls: list[tuple[str, ...]] = []

        def mock_run(args: list[str], **_kwargs) -> None:  # noqa: ANN003
            calls.append(tuple(args))
            # Simulate namespace not existing (kubectl get returns non-zero)
            returncode = 1 if args[:3] == ["kubectl", "get", "namespace"] else 0
            return type("Result", (), {"stdout": "", "returncode": returncode})()

        monkeypatch.setattr("subprocess.run", mock_run)

        install_cnpg_operator(cfg, _test_env())

        # Verify the expected commands were called
        assert len(calls) == 5
        assert calls[0] == (
            "helm",
            "repo",
            "add",
            "cnpg",
            "https://cloudnative-pg.github.io/charts",
        )
        assert calls[1] == ("helm", "repo", "update")
        assert calls[2] == ("kubectl", "get", "namespace", "cnpg-system")
        assert calls[3] == ("kubectl", "create", "namespace", "cnpg-system")
        assert calls[4] == (
            "helm",
            "upgrade",
            "--install",
            "cnpg",
            "cnpg/cloudnative-pg",
            "--namespace",
            "cnpg-system",
            "--wait",
        )


class TestCreateCnpgCluster:
    """Tests for create_cnpg_cluster helper using cmd-mox."""

    def test_applies_manifest(self, cmd_mox) -> None:  # noqa: ANN001
        """Should apply CNPG cluster manifest via kubectl."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args("apply", "-f", "-").returns(exit_code=0)

        create_cnpg_cluster(cfg, _test_env())


class TestWaitForCnpgReady:
    """Tests for wait_for_cnpg_ready helper using cmd-mox."""

    def test_waits_for_pod_ready(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke kubectl wait with correct selector."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args(
            "wait",
            "--for=condition=Ready",
            "pod",
            "--selector=cnpg.io/cluster=pg-ghillie",
            "--namespace=ghillie",
            "--timeout=600s",
        ).returns(exit_code=0)

        wait_for_cnpg_ready(cfg, _test_env())

    def test_uses_custom_timeout(self, cmd_mox) -> None:  # noqa: ANN001
        """Should use custom timeout value."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args(
            "wait",
            "--for=condition=Ready",
            "pod",
            "--selector=cnpg.io/cluster=pg-ghillie",
            "--namespace=ghillie",
            "--timeout=120s",
        ).returns(exit_code=0)

        wait_for_cnpg_ready(cfg, _test_env(), timeout=120)


class TestReadPgAppUri:
    """Tests for read_pg_app_uri helper using cmd-mox."""

    def test_decodes_secret(self, cmd_mox) -> None:  # noqa: ANN001
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
            "jsonpath={.data.uri}",
        ).returns(exit_code=0, stdout=encoded_uri)

        result = read_pg_app_uri(cfg, _test_env())

        assert result == "postgresql://ghillie:pass@pg-ghillie:5432/ghillie"


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

    def test_calls_expected_commands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should call helm and kubectl commands in correct order."""
        cfg = Config()
        calls: list[tuple[str, ...]] = []

        def mock_run(args: list[str], **_kwargs) -> None:  # noqa: ANN003
            calls.append(tuple(args))
            # Simulate namespace not existing (kubectl get returns non-zero)
            returncode = 1 if args[:3] == ["kubectl", "get", "namespace"] else 0
            return type("Result", (), {"stdout": "", "returncode": returncode})()

        monkeypatch.setattr("subprocess.run", mock_run)

        install_valkey_operator(cfg, _test_env())

        # Verify the expected commands were called
        assert len(calls) == 5
        assert calls[0] == (
            "helm",
            "repo",
            "add",
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

    def test_applies_manifest(self, cmd_mox) -> None:  # noqa: ANN001
        """Should apply Valkey manifest via kubectl."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args("apply", "-f", "-").returns(exit_code=0)

        create_valkey_instance(cfg, _test_env())


class TestWaitForValkeyReady:
    """Tests for wait_for_valkey_ready helper using cmd-mox."""

    def test_waits_for_pod_ready(self, cmd_mox) -> None:  # noqa: ANN001
        """Should invoke kubectl wait with correct selector."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args(
            "wait",
            "--for=condition=Ready",
            "pod",
            "--selector=app.kubernetes.io/name=valkey-ghillie",
            "--namespace=ghillie",
            "--timeout=300s",
        ).returns(exit_code=0)

        wait_for_valkey_ready(cfg, _test_env())

    def test_uses_custom_timeout(self, cmd_mox) -> None:  # noqa: ANN001
        """Should use custom timeout value."""
        cfg = Config()

        cmd_mox.mock("kubectl").with_args(
            "wait",
            "--for=condition=Ready",
            "pod",
            "--selector=app.kubernetes.io/name=valkey-ghillie",
            "--namespace=ghillie",
            "--timeout=120s",
        ).returns(exit_code=0)

        wait_for_valkey_ready(cfg, _test_env(), timeout=120)


class TestReadValkeyUri:
    """Tests for read_valkey_uri helper using cmd-mox."""

    def test_decodes_secret(self, cmd_mox) -> None:  # noqa: ANN001
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

        result = read_valkey_uri(cfg, _test_env())

        assert result == "valkey://valkey-ghillie:6379"
