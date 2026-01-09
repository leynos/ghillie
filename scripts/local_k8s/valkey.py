"""Valkey operations."""

from __future__ import annotations

import subprocess
import typing as typ

from local_k8s.config import HelmOperatorSpec
from local_k8s.operators import install_helm_operator
from local_k8s.validation import b64decode_k8s_secret_field

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
    return f"""\
apiVersion: valkey.io/v1alpha1
kind: Valkey
metadata:
  name: {valkey_name}
  namespace: {namespace}
spec:
  replicas: 1
  resources:
    requests:
      memory: "64Mi"
      cpu: "50m"
"""


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
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],  # noqa: S607
        input=manifest,
        text=True,
        check=True,
        env=env,
    )


def wait_for_valkey_ready(cfg: Config, env: dict[str, str], timeout: int = 300) -> None:
    """Wait for the Valkey pods to be ready.

    Uses kubectl wait to block until all pods matching the Valkey label
    are in Ready condition.

    Args:
        cfg: Configuration with namespace and Valkey name.
        env: Environment dict with KUBECONFIG set.
        timeout: Maximum time to wait in seconds (default 300).

    """
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "wait",
            "--for=condition=Ready",
            "pod",
            f"--selector=app.kubernetes.io/name={cfg.valkey_name}",
            f"--namespace={cfg.namespace}",
            f"--timeout={timeout}s",
        ],
        check=True,
        env=env,
    )


def read_valkey_uri(cfg: Config, env: dict[str, str]) -> str:
    """Extract VALKEY_URL from the Valkey secret.

    The Valkey operator creates a secret with connection information
    for applications.

    Args:
        cfg: Configuration with namespace and Valkey name.
        env: Environment dict with KUBECONFIG set.

    Returns:
        The decoded VALKEY_URL connection string.

    """
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "get",
            "secret",
            cfg.valkey_name,
            f"--namespace={cfg.namespace}",
            "-o",
            "jsonpath={.data.uri}",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return b64decode_k8s_secret_field(result.stdout)
