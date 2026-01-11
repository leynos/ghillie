"""CloudNativePG (CNPG) operator and cluster operations.

Provides functions for installing the CloudNativePG operator via Helm,
creating PostgreSQL database clusters using CNPG CustomResourceDefinitions,
and reading connection information from CNPG-managed secrets.

Public API:
    cnpg_cluster_manifest: Generate a CNPG Cluster YAML manifest.
    install_cnpg_operator: Install the CNPG operator Helm chart.
    create_cnpg_cluster: Deploy a CNPG Cluster CR to the cluster.
    wait_for_cnpg_ready: Block until CNPG pods are ready.
    read_pg_app_uri: Read the Postgres connection URI from CNPG secret.

Example:
    >>> cfg = Config()
    >>> env = kubeconfig_env("ghillie-local")
    >>> install_cnpg_operator(cfg, env)
    >>> create_cnpg_cluster(cfg, env)
    >>> wait_for_cnpg_ready(cfg, env)
    >>> uri = read_pg_app_uri(cfg, env)

Note:
    The namespace must exist before calling create_cnpg_cluster. Use
    ensure_namespace() from local_k8s.k8s to create it if needed.

"""

from __future__ import annotations

import io
import json
import subprocess
import typing as typ

from ruamel.yaml import YAML

from local_k8s.config import HelmOperatorSpec
from local_k8s.k8s import apply_manifest, read_secret_field, wait_for_pods_ready
from local_k8s.operators import install_helm_operator
from local_k8s.validation import LocalK8sError

if typ.TYPE_CHECKING:
    from local_k8s.config import Config


def cnpg_cluster_manifest(namespace: str, cluster_name: str = "pg-ghillie") -> str:
    """Generate a CNPG Cluster YAML manifest.

    Args:
        namespace: Kubernetes namespace for the cluster.
        cluster_name: Name for the Postgres cluster resource.

    Returns:
        YAML manifest string for the CNPG Cluster resource.

    """
    manifest = {
        "apiVersion": "postgresql.cnpg.io/v1",
        "kind": "Cluster",
        "metadata": {
            "name": cluster_name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "local_k8s",
                "app.kubernetes.io/name": "cnpg-cluster",
                "app.kubernetes.io/instance": cluster_name,
                "app.kubernetes.io/component": "database",
            },
        },
        "spec": {
            "instances": 1,
            "storage": {"size": "1Gi"},
            "bootstrap": {"initdb": {"database": "ghillie", "owner": "ghillie"}},
        },
    }
    yaml_serializer = YAML(typ="safe")
    yaml_serializer.default_flow_style = False
    yaml_serializer.indent(mapping=2, sequence=4, offset=2)
    with io.StringIO() as stream:
        yaml_serializer.dump(manifest, stream)
        return stream.getvalue()


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
    manifest = cnpg_cluster_manifest(cfg.namespace, cfg.pg_cluster_name)
    apply_manifest(manifest, env)


def _check_pods_exist(selector: str, namespace: str, env: dict[str, str]) -> bool:
    """Check if any pods match the given label selector.

    Parameters
    ----------
    selector : str
        Label selector for pods (e.g., "cnpg.io/cluster=pg-ghillie").
    namespace : str
        Kubernetes namespace to search in.
    env : dict[str, str]
        Environment dict with KUBECONFIG set.

    Returns
    -------
    bool
        True if at least one pod exists matching the selector.

    """
    # S603/S607: kubectl via PATH is standard; selector/namespace from Config
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "get",
            "pods",
            f"--selector={selector}",
            f"--namespace={namespace}",
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout)
        return len(data.get("items", [])) > 0
    except json.JSONDecodeError:
        return False


def wait_for_cnpg_ready(cfg: Config, env: dict[str, str], timeout: int = 600) -> None:
    """Wait for the CNPG Postgres cluster pods to be ready.

    Uses kubectl wait to block until all pods matching the cluster label
    are in Ready condition. Performs a pre-flight check to verify pods exist
    before waiting, providing clearer error messages for common failure modes.

    Parameters
    ----------
    cfg : Config
        Configuration with namespace and cluster name.
    env : dict[str, str]
        Environment dict with KUBECONFIG set.
    timeout : int, default 600
        Maximum time to wait in seconds. Must be between 1 and 3600.

    Raises
    ------
    ValueError
        If timeout is outside the valid range (1-3600 seconds).
    LocalK8sError
        If no pods exist for the cluster (likely the Cluster CR was not created
        or the CNPG operator is not running), or if the wait times out.

    """
    selector = f"cnpg.io/cluster={cfg.pg_cluster_name}"

    # Pre-flight check: verify pods exist before waiting
    if not _check_pods_exist(selector, cfg.namespace, env):
        msg = (
            f"CNPG cluster '{cfg.pg_cluster_name}' has no pods in namespace "
            f"'{cfg.namespace}'. Ensure the CNPG Cluster resource was created "
            "and the CNPG operator is running."
        )
        raise LocalK8sError(msg)

    try:
        wait_for_pods_ready(selector, cfg.namespace, env, timeout)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        if "timed out" in stderr.lower():
            msg = (
                f"Timeout waiting for CNPG cluster '{cfg.pg_cluster_name}' pods "
                f"to become ready after {timeout}s. Check pod logs for issues: "
                f"kubectl logs -l {selector} -n {cfg.namespace}"
            )
        else:
            msg = (
                f"Failed waiting for CNPG cluster '{cfg.pg_cluster_name}' pods: "
                f"{stderr or e}"
            )
        raise LocalK8sError(msg) from e


def read_pg_app_uri(cfg: Config, env: dict[str, str]) -> str:
    """Read the Postgres connection URI from the CNPG application secret.

    CNPG automatically creates a secret named `{cluster_name}-app` containing
    the connection URI under the `uri` key. This function retrieves and decodes
    that value for use as a DATABASE_URL.

    Args:
        cfg: Configuration with namespace and cluster name.
        env: Environment dict with KUBECONFIG set.

    Returns:
        The decoded Postgres connection URI string
        (e.g., "postgresql://user:pass@host:5432/db").

    Raises:
        ValueError: If the secret '{cfg.pg_cluster_name}-app' field 'uri' is
            empty or missing in namespace '{cfg.namespace}'.

    """
    secret_name = f"{cfg.pg_cluster_name}-app"
    return read_secret_field(secret_name, "uri", cfg.namespace, env)
