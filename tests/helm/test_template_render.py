"""Unit tests for Helm chart template rendering."""

from __future__ import annotations

import shutil
import subprocess
import typing as typ

import pytest
from ruamel.yaml import YAML

if typ.TYPE_CHECKING:
    from pathlib import Path


def _run_helm_template(
    chart: Path,
    values_file: Path | None = None,
    set_values: dict[str, str] | None = None,
) -> list[dict]:
    """Run helm template and return parsed YAML documents.

    Args:
        chart: Path to the Helm chart directory.
        values_file: Optional path to a values file.
        set_values: Optional dictionary of --set key=value pairs.

    Returns:
        List of parsed Kubernetes manifest dictionaries.

    Raises:
        pytest.Failed: If helm template command fails.

    """
    if shutil.which("helm") is None:
        pytest.skip("helm is not installed")

    cmd = ["helm", "template", "test-release", str(chart)]

    if values_file:
        cmd.extend(["--values", str(values_file)])

    for key, value in (set_values or {}).items():
        cmd.extend(["--set", f"{key}={value}"])

    result = subprocess.run(  # noqa: S603 - static helm invocation
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        pytest.fail(f"helm template failed: {result.stderr}")

    yaml_parser = YAML()
    yaml_parser.preserve_quotes = True
    docs = list(yaml_parser.load_all(result.stdout))
    return [d for d in docs if d is not None]


def _get_resources_by_kind(docs: list[dict], kind: str) -> list[dict]:
    """Filter documents by Kubernetes resource kind.

    Args:
        docs: List of parsed Kubernetes manifest dictionaries.
        kind: The Kubernetes resource kind to filter by (e.g., "Deployment").

    Returns:
        List of documents matching the specified kind.

    """
    return [d for d in docs if d["kind"] == kind]


def _assert_resource_count(
    docs: list[dict], kind: str, expected_count: int
) -> list[dict]:
    """Assert the count of resources by kind and return the filtered list.

    Args:
        docs: List of parsed Kubernetes manifest dictionaries.
        kind: The Kubernetes resource kind to filter by.
        expected_count: Expected number of resources of this kind.

    Returns:
        List of documents matching the specified kind.

    Raises:
        AssertionError: If the count doesn't match expected_count.

    """
    resources = _get_resources_by_kind(docs, kind)
    assert len(resources) == expected_count
    return resources


class TestDeploymentRendering:
    """Tests for Deployment template rendering."""

    def test_deployment_uses_correct_image(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Deployment should use the configured image."""
        docs = _run_helm_template(
            chart_path,
            set_values={
                "image.repository": "ghcr.io/test/ghillie",
                "image.tag": "v1.0.0",
            },
        )

        deployments = _assert_resource_count(docs, "Deployment", 1)

        container = deployments[0]["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "ghcr.io/test/ghillie:v1.0.0"

    def test_deployment_uses_default_image(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Deployment should use default image values."""
        docs = _run_helm_template(chart_path)

        deployments = _get_resources_by_kind(docs, "Deployment")
        container = deployments[0]["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "ghillie:local"

    def test_deployment_command_override(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Deployment should use command override when specified."""
        docs = _run_helm_template(
            chart_path,
            set_values={
                "command[0]": "python",
                "command[1]": "-m",
                "command[2]": "ghillie.worker",
            },
        )

        deployments = _get_resources_by_kind(docs, "Deployment")
        container = deployments[0]["spec"]["template"]["spec"]["containers"][0]
        assert container.get("command") == ["python", "-m", "ghillie.worker"]

    def test_deployment_env_from_secret(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Deployment should load env from secret."""
        docs = _run_helm_template(chart_path)

        deployments = _get_resources_by_kind(docs, "Deployment")
        container = deployments[0]["spec"]["template"]["spec"]["containers"][0]

        env_from = container.get("envFrom", [])
        secret_refs = [e for e in env_from if "secretRef" in e]
        assert len(secret_refs) == 1

    def test_deployment_uses_existing_secret_name(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Deployment should use existingSecretName when provided."""
        docs = _run_helm_template(
            chart_path,
            set_values={"secrets.existingSecretName": "my-custom-secret"},
        )

        deployments = _get_resources_by_kind(docs, "Deployment")
        container = deployments[0]["spec"]["template"]["spec"]["containers"][0]

        env_from = container.get("envFrom", [])
        secret_ref = env_from[0]["secretRef"]["name"]
        assert secret_ref == "my-custom-secret"  # noqa: S105 - test fixture value

    def test_deployment_injects_env_normal(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Deployment should inject env.normal values."""
        docs = _run_helm_template(chart_path)

        deployments = _get_resources_by_kind(docs, "Deployment")
        container = deployments[0]["spec"]["template"]["spec"]["containers"][0]

        env_vars = {e["name"]: e["value"] for e in container.get("env", [])}
        assert "GHILLIE_ENV" in env_vars
        assert env_vars["GHILLIE_ENV"] == "development"


class TestServiceRendering:
    """Tests for Service template rendering."""

    def test_service_uses_configured_port(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Service should use the configured port."""
        docs = _run_helm_template(
            chart_path,
            set_values={"service.port": "9090"},
        )

        services = _assert_resource_count(docs, "Service", 1)
        assert services[0]["spec"]["ports"][0]["port"] == 9090

    def test_service_default_type_is_clusterip(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Service type should default to ClusterIP."""
        docs = _run_helm_template(chart_path)

        services = _get_resources_by_kind(docs, "Service")
        assert services[0]["spec"]["type"] == "ClusterIP"


class TestIngressRendering:
    """Tests for Ingress template rendering."""

    def test_ingress_disabled(self, chart_path: Path, require_helm: None) -> None:
        """Ingress should not render when disabled."""
        docs = _run_helm_template(
            chart_path,
            set_values={"ingress.enabled": "false"},
        )

        _assert_resource_count(docs, "Ingress", 0)

    def test_ingress_enabled_by_default(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Ingress should render when enabled (default)."""
        docs = _run_helm_template(chart_path)

        _assert_resource_count(docs, "Ingress", 1)

    def test_ingress_hostless_for_local(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Ingress should support empty host for local k3d."""
        docs = _run_helm_template(chart_path)

        ingresses = _assert_resource_count(docs, "Ingress", 1)

        rules = ingresses[0]["spec"]["rules"]
        assert len(rules) == 1
        # Empty host means no "host" key in the rule
        assert "host" not in rules[0]

    def test_ingress_with_explicit_host(
        self, chart_path: Path, fixtures_path: Path, require_helm: None
    ) -> None:
        """Ingress should use explicit hostname when provided."""
        docs = _run_helm_template(
            chart_path,
            values_file=fixtures_path / "values_gitops.yaml",
        )

        ingresses = _get_resources_by_kind(docs, "Ingress")
        rules = ingresses[0]["spec"]["rules"]
        assert rules[0]["host"] == "pr-123.preview.example.com"

    def test_ingress_with_classname(self, chart_path: Path, require_helm: None) -> None:
        """Ingress should set ingressClassName when configured."""
        docs = _run_helm_template(
            chart_path,
            set_values={"ingress.className": "nginx"},
        )

        ingresses = _get_resources_by_kind(docs, "Ingress")
        assert ingresses[0]["spec"]["ingressClassName"] == "nginx"


class TestExternalSecretRendering:
    """Tests for ExternalSecret template rendering."""

    def test_externalsecret_disabled_by_default(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """ExternalSecret should not render when disabled."""
        docs = _run_helm_template(chart_path)

        _assert_resource_count(docs, "ExternalSecret", 0)

    def test_externalsecret_renders_when_enabled(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """ExternalSecret should render when enabled."""
        docs = _run_helm_template(
            chart_path,
            set_values={
                "secrets.externalSecret.enabled": "true",
                "secrets.externalSecret.secretStoreRef": "platform-vault",
            },
        )

        external_secrets = _assert_resource_count(docs, "ExternalSecret", 1)
        assert external_secrets[0]["spec"]["secretStoreRef"]["name"] == "platform-vault"

    def test_externalsecret_target_name(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """ExternalSecret target name should match fullname."""
        docs = _run_helm_template(
            chart_path,
            set_values={
                "secrets.externalSecret.enabled": "true",
                "secrets.externalSecret.secretStoreRef": "platform-vault",
            },
        )

        external_secrets = _get_resources_by_kind(docs, "ExternalSecret")
        target_name = external_secrets[0]["spec"]["target"]["name"]
        assert target_name == "test-release-ghillie"


class TestServiceAccountRendering:
    """Tests for ServiceAccount template rendering."""

    def test_serviceaccount_created_by_default(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """ServiceAccount should be created by default."""
        docs = _run_helm_template(chart_path)

        _assert_resource_count(docs, "ServiceAccount", 1)

    def test_serviceaccount_not_created_when_disabled(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """ServiceAccount should not be created when disabled."""
        docs = _run_helm_template(
            chart_path,
            set_values={"serviceAccount.create": "false"},
        )

        _assert_resource_count(docs, "ServiceAccount", 0)

    def test_deployment_uses_default_serviceaccount(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Deployment should reference the created ServiceAccount by default."""
        docs = _run_helm_template(chart_path)

        deployments = _get_resources_by_kind(docs, "Deployment")
        pod_spec = deployments[0]["spec"]["template"]["spec"]
        assert pod_spec["serviceAccountName"] == "test-release-ghillie"

    def test_deployment_serviceaccount_with_custom_name(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """Deployment should use custom serviceAccount.name when provided."""
        docs = _run_helm_template(
            chart_path,
            set_values={"serviceAccount.name": "my-custom-sa"},
        )

        deployments = _get_resources_by_kind(docs, "Deployment")
        pod_spec = deployments[0]["spec"]["template"]["spec"]
        assert pod_spec["serviceAccountName"] == "my-custom-sa"


class TestConfigMapRendering:
    """Tests for ConfigMap template rendering."""

    def test_configmap_created_with_env_normal(
        self, chart_path: Path, require_helm: None
    ) -> None:
        """ConfigMap should be created when env.normal has values."""
        docs = _run_helm_template(chart_path)

        configmaps = _assert_resource_count(docs, "ConfigMap", 1)
        assert "GHILLIE_ENV" in configmaps[0]["data"]

    def test_configmap_not_created_with_empty_env_normal(
        self, chart_path: Path, fixtures_path: Path, require_helm: None
    ) -> None:
        """ConfigMap should not be created when env.normal is empty."""
        docs = _run_helm_template(
            chart_path,
            values_file=fixtures_path / "values_empty_env.yaml",
        )

        _assert_resource_count(docs, "ConfigMap", 0)


class TestHelmLint:
    """Tests for Helm lint validation."""

    def test_chart_passes_helm_lint(self, chart_path: Path, require_helm: None) -> None:
        """Chart should pass helm lint."""
        result = subprocess.run(  # noqa: S603 - static helm invocation
            ["helm", "lint", str(chart_path)],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"helm lint failed: {result.stdout}"
