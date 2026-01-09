"""CloudNativePG operations."""

from __future__ import annotations

import subprocess
import typing as typ

from local_k8s.config import HelmOperatorSpec
from local_k8s.operators import install_helm_operator
from local_k8s.validation import b64decode_k8s_secret_field

if typ.TYPE_CHECKING:
    from local_k8s.config import Config


def _cnpg_cluster_manifest(namespace: str, cluster_name: str = "pg-ghillie") -> str:
    """Generate a CNPG Cluster YAML manifest.

    Args:
        namespace: Kubernetes namespace for the cluster.
        cluster_name: Name for the Postgres cluster resource.

    Returns:
        YAML manifest string for the CNPG Cluster resource.

    """
    return f"""\
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: {cluster_name}
  namespace: {namespace}
spec:
  instances: 1
  storage:
    size: 1Gi
  bootstrap:
    initdb:
      database: ghillie
      owner: ghillie
"""


def install_cnpg_operator(cfg: Config, env: dict[str, str]) -> None:
    """Install the CloudNativePG operator via Helm.

    Adds the CNPG Helm repository and installs the operator chart
    into its dedicated namespace.

    Args:
        cfg: Configuration with CNPG release name and namespace.
        env: Environment dict with KUBECONFIG set.

    """
    spec = HelmOperatorSpec(
        repo_name="cnpg",
        repo_url="https://cloudnative-pg.github.io/charts",
        release_name=cfg.cnpg_release,
        chart_name="cnpg/cloudnative-pg",
        namespace=cfg.cnpg_namespace,
    )
    install_helm_operator(spec, env)


def create_cnpg_cluster(cfg: Config, env: dict[str, str]) -> None:
    """Create a CNPG Postgres cluster by applying a manifest.

    Generates and applies the CNPG Cluster manifest to the target namespace.

    Args:
        cfg: Configuration with namespace and cluster name.
        env: Environment dict with KUBECONFIG set.

    """
    manifest = _cnpg_cluster_manifest(cfg.namespace, cfg.pg_cluster_name)
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],  # noqa: S607
        input=manifest,
        text=True,
        check=True,
        env=env,
    )


def wait_for_cnpg_ready(cfg: Config, env: dict[str, str], timeout: int = 600) -> None:
    """Wait for the CNPG Postgres cluster pods to be ready.

    Uses kubectl wait to block until all pods matching the cluster label
    are in Ready condition.

    Args:
        cfg: Configuration with namespace and cluster name.
        env: Environment dict with KUBECONFIG set.
        timeout: Maximum time to wait in seconds (default 600).

    """
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "wait",
            "--for=condition=Ready",
            "pod",
            f"--selector=cnpg.io/cluster={cfg.pg_cluster_name}",
            f"--namespace={cfg.namespace}",
            f"--timeout={timeout}s",
        ],
        check=True,
        env=env,
    )


def read_pg_app_uri(cfg: Config, env: dict[str, str]) -> str:
    """Extract DATABASE_URL from the CNPG application secret.

    CNPG creates a secret named {cluster_name}-app containing the
    connection URI for applications.

    Args:
        cfg: Configuration with namespace and cluster name.
        env: Environment dict with KUBECONFIG set.

    Returns:
        The decoded DATABASE_URL connection string.

    """
    secret_name = f"{cfg.pg_cluster_name}-app"
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "get",
            "secret",
            secret_name,
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
