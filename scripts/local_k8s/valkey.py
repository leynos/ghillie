"""Valkey operations."""

from __future__ import annotations

import io
import typing as typ

from ruamel.yaml import YAML

from local_k8s.config import HelmOperatorSpec
from local_k8s.k8s import apply_manifest, read_secret_field, wait_for_pods_ready
from local_k8s.operators import install_helm_operator

if typ.TYPE_CHECKING:
    from local_k8s.config import Config


def _valkey_manifest(namespace: str, valkey_name: str = "valkey-ghillie") -> str:
    """Generate a Valkey CR YAML manifest.

    Args:
        namespace: Kubernetes namespace for the Valkey instance.
        valkey_name: Name for the Valkey resource.

    Returns:
        YAML manifest string for the Valkey resource.

    """
    manifest = {
        "apiVersion": "valkey.io/v1alpha1",
        "kind": "Valkey",
        "metadata": {
            "name": valkey_name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "local_k8s",
                "app.kubernetes.io/name": "valkey",
                "app.kubernetes.io/instance": valkey_name,
                "app.kubernetes.io/component": "cache",
            },
        },
        "spec": {
            "replicas": 1,
            "resources": {
                "requests": {
                    "memory": "64Mi",
                    "cpu": "50m",
                },
            },
        },
    }
    yaml_serializer = YAML(typ="safe")
    yaml_serializer.default_flow_style = False
    yaml_serializer.indent(mapping=2, sequence=4, offset=2)
    stream = io.StringIO()
    yaml_serializer.dump(manifest, stream)
    return stream.getvalue()


def install_valkey_operator(cfg: Config, env: dict[str, str]) -> None:
    """Install the Valkey operator via Helm.

    Adds the hyperspike Helm repository and installs the valkey-operator chart
    into its dedicated namespace.

    Args:
        cfg: Configuration with Valkey release name and namespace.
        env: Environment dict with KUBECONFIG set.

    """
    spec = HelmOperatorSpec(
        repo_name="valkey-operator",
        repo_url="https://hyperspike.github.io/valkey-operator",
        release_name=cfg.valkey_release,
        chart_name="valkey-operator/valkey-operator",
        namespace=cfg.valkey_namespace,
    )
    install_helm_operator(spec, env)


def create_valkey_instance(cfg: Config, env: dict[str, str]) -> None:
    """Create a Valkey instance by applying a manifest.

    Generates and applies the Valkey CR manifest to the target namespace.

    Args:
        cfg: Configuration with namespace and Valkey name.
        env: Environment dict with KUBECONFIG set.

    """
    manifest = _valkey_manifest(cfg.namespace, cfg.valkey_name)
    apply_manifest(manifest, env)


def wait_for_valkey_ready(cfg: Config, env: dict[str, str], timeout: int = 300) -> None:
    """Wait for the Valkey pods to be ready.

    Uses kubectl wait to block until all pods matching the Valkey label
    are in Ready condition.

    Args:
        cfg: Configuration with namespace and Valkey name.
        env: Environment dict with KUBECONFIG set.
        timeout: Maximum time to wait in seconds (default 300). Must be between
            1 and 3600.

    Raises:
        ValueError: If timeout is outside the valid range.

    """
    selector = f"app.kubernetes.io/name={cfg.valkey_name}"
    wait_for_pods_ready(selector, cfg.namespace, env, timeout)


def read_valkey_uri(cfg: Config, env: dict[str, str]) -> str:
    """Extract VALKEY_URL from the Valkey secret.

    The Valkey operator creates a secret with connection information
    for applications.

    Args:
        cfg: Configuration with namespace and Valkey name.
        env: Environment dict with KUBECONFIG set.

    Returns:
        The decoded VALKEY_URL connection string.

    Raises:
        ValueError: If the secret field is empty or missing.

    """
    return read_secret_field(cfg.valkey_name, "uri", cfg.namespace, env)
