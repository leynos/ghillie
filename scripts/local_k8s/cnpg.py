"""CloudNativePG operations."""

from __future__ import annotations

import typing as typ

from local_k8s.config import HelmOperatorSpec
from local_k8s.k8s import apply_manifest, read_secret_field, wait_for_pods_ready
from local_k8s.operators import install_helm_operator

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
    apply_manifest(manifest, env)


def wait_for_cnpg_ready(cfg: Config, env: dict[str, str], timeout: int = 600) -> None:
    """Wait for the CNPG Postgres cluster pods to be ready.

    Uses kubectl wait to block until all pods matching the cluster label
    are in Ready condition.

    Args:
        cfg: Configuration with namespace and cluster name.
        env: Environment dict with KUBECONFIG set.
        timeout: Maximum time to wait in seconds (default 600). Must be between
            1 and 3600.

    Raises:
        ValueError: If timeout is outside the valid range.

    """
    selector = f"cnpg.io/cluster={cfg.pg_cluster_name}"
    wait_for_pods_ready(selector, cfg.namespace, env, timeout)


def read_pg_app_uri(cfg: Config, env: dict[str, str]) -> str:
    """Extract DATABASE_URL from the CNPG application secret.

    CNPG creates a secret named {cluster_name}-app containing the
    connection URI for applications.

    Args:
        cfg: Configuration with namespace and cluster name.
        env: Environment dict with KUBECONFIG set.

    Returns:
        The decoded DATABASE_URL connection string.

    Raises:
        ValueError: If the secret field is empty or missing.

    """
    secret_name = f"{cfg.pg_cluster_name}-app"
    return read_secret_field(secret_name, "uri", cfg.namespace, env)
