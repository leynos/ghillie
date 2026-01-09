#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.13"
# dependencies = ["cyclopts>=2.9"]
# ///
"""Local k3d preview environment management for Ghillie.

This script provides subcommands for creating and managing a local k3d-based
preview environment that mirrors the ephemeral previews architecture.

Usage:
    uv run scripts/local_k8s.py up      # Create preview environment
    uv run scripts/local_k8s.py down    # Delete preview environment
    uv run scripts/local_k8s.py status  # Show environment status
    uv run scripts/local_k8s.py logs    # Tail application logs

Environment variables:
    GHILLIE_K3D_CLUSTER   - Cluster name (default: ghillie-local)
    GHILLIE_K3D_NAMESPACE - Kubernetes namespace (default: ghillie)
    GHILLIE_K3D_PORT      - Host port for ingress (default: auto-selected)
"""

from __future__ import annotations

import base64
import dataclasses
import json
import os
import shutil
import socket
import subprocess
import sys
import typing as typ
from pathlib import Path

from cyclopts import App, Parameter

app = App(
    name="local_k8s",
    help="Local k3d preview environment for Ghillie",
    version="0.1.0",
)


@dataclasses.dataclass(frozen=True, slots=True)
class Config:
    """Configuration for the local k3d preview environment.

    All paths are relative to the repository root unless absolute.
    """

    cluster_name: str = "ghillie-local"
    namespace: str = "ghillie"
    ingress_port: int | None = None
    chart_path: Path = dataclasses.field(default_factory=lambda: Path("charts/ghillie"))
    image_repo: str = "ghillie"
    image_tag: str = "local"
    cnpg_release: str = "cnpg"
    cnpg_namespace: str = "cnpg-system"
    valkey_release: str = "valkey-operator"
    valkey_namespace: str = "valkey-operator-system"
    values_file: Path = dataclasses.field(
        default_factory=lambda: Path("tests/helm/fixtures/values_local.yaml")
    )
    pg_cluster_name: str = "pg-ghillie"
    valkey_name: str = "valkey-ghillie"
    app_secret_name: str = "ghillie"  # noqa: S105


# =============================================================================
# Helper functions
# =============================================================================


class ExecutableNotFoundError(Exception):
    """Required CLI tool is not installed."""


def require_exe(name: str) -> None:
    """Verify a CLI tool is available in PATH.

    Args:
        name: Name of the executable to check for.

    Raises:
        ExecutableNotFoundError: If the executable is not found in PATH.

    """
    if shutil.which(name) is None:
        msg = f"Required executable '{name}' not found in PATH"
        raise ExecutableNotFoundError(msg)


def pick_free_loopback_port() -> int:
    """Find an available TCP port on 127.0.0.1.

    Uses the kernel's ephemeral port allocation by binding to port 0,
    which causes the OS to assign an available port.

    Returns:
        An available port number on the loopback interface.

    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def b64decode_k8s_secret_field(b64_text: str) -> str:
    """Decode a base64-encoded Kubernetes secret value.

    Kubernetes secrets store values as base64-encoded strings. This function
    decodes them to UTF-8 text.

    Args:
        b64_text: Base64-encoded string from a Kubernetes secret.

    Returns:
        The decoded UTF-8 string.

    """
    return base64.b64decode(b64_text).decode("utf-8")


# =============================================================================
# k3d cluster lifecycle
# =============================================================================


def cluster_exists(cluster_name: str) -> bool:
    """Check if a k3d cluster already exists.

    Args:
        cluster_name: Name of the cluster to check for.

    Returns:
        True if the cluster exists, False otherwise.

    """
    result = subprocess.run(
        ["k3d", "cluster", "list", "-o", "json"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    clusters = json.loads(result.stdout)
    return any(c.get("name") == cluster_name for c in clusters)


def create_k3d_cluster(cluster_name: str, port: int, agents: int = 1) -> None:
    """Create a k3d cluster with loopback port mapping.

    Creates a k3d cluster configured with:
    - Specified number of agent nodes
    - Port mapping from loopback (127.0.0.1) to Traefik on port 80

    Args:
        cluster_name: Name for the new cluster.
        port: Host port to map to ingress (port 80 on the load balancer).
        agents: Number of agent nodes (default 1).

    """
    port_mapping = f"127.0.0.1:{port}:80@loadbalancer"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "k3d",
            "cluster",
            "create",
            cluster_name,
            "--agents",
            str(agents),
            "--port",
            port_mapping,
        ],
        check=True,
    )


def delete_k3d_cluster(cluster_name: str) -> None:
    """Delete a k3d cluster.

    Args:
        cluster_name: Name of the cluster to delete.

    """
    subprocess.run(  # noqa: S603
        ["k3d", "cluster", "delete", cluster_name],  # noqa: S607
        check=True,
    )


def write_kubeconfig(cluster_name: str) -> Path:
    """Write and return the kubeconfig path for a k3d cluster.

    Uses k3d's kubeconfig write command to generate a dedicated kubeconfig
    file for the specified cluster.

    Args:
        cluster_name: Name of the k3d cluster.

    Returns:
        Path to the generated kubeconfig file.

    """
    result = subprocess.run(  # noqa: S603
        ["k3d", "kubeconfig", "write", cluster_name],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def kubeconfig_env(cluster_name: str) -> dict[str, str]:
    """Return environment dict with KUBECONFIG set for the cluster.

    Creates a copy of the current environment with KUBECONFIG pointing to
    the cluster's kubeconfig file.

    Args:
        cluster_name: Name of the k3d cluster.

    Returns:
        Environment dictionary with KUBECONFIG set.

    """
    kubeconfig = write_kubeconfig(cluster_name)
    env = dict(os.environ)
    env["KUBECONFIG"] = str(kubeconfig)
    return env


# =============================================================================
# Kubernetes namespace helpers
# =============================================================================


def namespace_exists(namespace: str, env: dict[str, str]) -> bool:
    """Check if a Kubernetes namespace exists.

    Args:
        namespace: Name of the namespace to check.
        env: Environment dict with KUBECONFIG set.

    Returns:
        True if the namespace exists, False otherwise.

    """
    result = subprocess.run(  # noqa: S603
        ["kubectl", "get", "namespace", namespace],  # noqa: S607
        capture_output=True,
        env=env,
    )
    return result.returncode == 0


def create_namespace(namespace: str, env: dict[str, str]) -> None:
    """Create a Kubernetes namespace.

    Args:
        namespace: Name of the namespace to create.
        env: Environment dict with KUBECONFIG set.

    """
    subprocess.run(  # noqa: S603
        ["kubectl", "create", "namespace", namespace],  # noqa: S607
        check=True,
        env=env,
    )


def ensure_namespace(namespace: str, env: dict[str, str]) -> None:
    """Ensure a Kubernetes namespace exists, creating if necessary.

    Args:
        namespace: Name of the namespace to ensure.
        env: Environment dict with KUBECONFIG set.

    """
    if not namespace_exists(namespace, env):
        create_namespace(namespace, env)


# =============================================================================
# Generic Helm operator installer
# =============================================================================


def install_helm_operator(  # noqa: PLR0913
    repo_name: str,
    repo_url: str,
    release_name: str,
    chart_name: str,
    namespace: str,
    env: dict[str, str],
) -> None:
    """Install a Helm operator with standard workflow.

    Adds repository, updates, ensures namespace, and installs chart.

    Args:
        repo_name: Helm repository alias.
        repo_url: Helm repository URL.
        release_name: Helm release name.
        chart_name: Fully qualified chart name (repo/chart).
        namespace: Target namespace for the operator.
        env: Environment dict with KUBECONFIG set.

    """
    subprocess.run(  # noqa: S603
        ["helm", "repo", "add", repo_name, repo_url],  # noqa: S607
        check=True,
        env=env,
    )
    subprocess.run(
        ["helm", "repo", "update"],  # noqa: S607
        check=True,
        env=env,
    )
    ensure_namespace(namespace, env)
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "helm",
            "upgrade",
            "--install",
            release_name,
            chart_name,
            "--namespace",
            namespace,
            "--wait",
        ],
        check=True,
        env=env,
    )


# =============================================================================
# CloudNativePG (CNPG) helpers
# =============================================================================


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
    install_helm_operator(
        "cnpg",
        "https://cloudnative-pg.github.io/charts",
        cfg.cnpg_release,
        "cnpg/cloudnative-pg",
        cfg.cnpg_namespace,
        env,
    )


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


# =============================================================================
# Valkey helpers
# =============================================================================


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
    install_helm_operator(
        "valkey-operator",
        "https://hyperspike.github.io/valkey-operator",
        cfg.valkey_release,
        "valkey-operator/valkey-operator",
        cfg.valkey_namespace,
        env,
    )


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


# =============================================================================
# Application secret and image helpers
# =============================================================================


def create_app_secret(
    cfg: Config,
    env: dict[str, str],
    database_url: str,
    valkey_url: str,
) -> None:
    """Create the Ghillie application Kubernetes Secret.

    Creates a generic secret containing DATABASE_URL and VALKEY_URL for
    the application to connect to Postgres and Valkey. Uses dry-run + apply
    pattern for idempotent upsert behavior.

    Args:
        cfg: Configuration with namespace and secret name.
        env: Environment dict with KUBECONFIG set.
        database_url: PostgreSQL connection URL from CNPG.
        valkey_url: Valkey connection URL.

    """
    # Generate secret YAML using dry-run
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "create",
            "secret",
            "generic",
            cfg.app_secret_name,
            f"--namespace={cfg.namespace}",
            f"--from-literal=DATABASE_URL={database_url}",
            f"--from-literal=VALKEY_URL={valkey_url}",
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    # Apply for idempotent upsert
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],  # noqa: S607
        input=result.stdout,
        text=True,
        check=True,
        env=env,
    )


def build_docker_image(image_repo: str, image_tag: str) -> None:
    """Build the Docker image locally.

    Builds the Ghillie Docker image from the Dockerfile in the repository root.

    Args:
        image_repo: Repository name for the image.
        image_tag: Tag for the image.

    """
    image_name = f"{image_repo}:{image_tag}"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "docker",
            "build",
            "-t",
            image_name,
            ".",
        ],
        check=True,
    )


def import_image_to_k3d(cluster_name: str, image_repo: str, image_tag: str) -> None:
    """Import a Docker image into the k3d cluster.

    Uses k3d's image import command to make a locally built image
    available to pods running in the cluster.

    Args:
        cluster_name: Name of the k3d cluster.
        image_repo: Repository name of the image.
        image_tag: Tag of the image.

    """
    image_name = f"{image_repo}:{image_tag}"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "k3d",
            "image",
            "import",
            image_name,
            "--cluster",
            cluster_name,
        ],
        check=True,
    )


# =============================================================================
# Helm chart installation helpers
# =============================================================================


def install_ghillie_chart(cfg: Config, env: dict[str, str]) -> None:
    """Install the Ghillie Helm chart.

    Uses helm upgrade --install for idempotent installation. The chart is
    installed from the local charts/ghillie directory using the local
    values file.

    Args:
        cfg: Configuration with chart path, namespace, and values file.
        env: Environment dict with KUBECONFIG set.

    """
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "helm",
            "upgrade",
            "--install",
            "ghillie",
            str(cfg.chart_path),
            "--namespace",
            cfg.namespace,
            "--values",
            str(cfg.values_file),
            "--set",
            f"image.repository={cfg.image_repo}",
            "--set",
            f"image.tag={cfg.image_tag}",
            "--wait",
        ],
        check=True,
        env=env,
    )


def print_status(cfg: Config, env: dict[str, str]) -> None:
    """Print pod status for the preview environment.

    Displays the status of all pods in the configured namespace using
    kubectl get pods.

    Args:
        cfg: Configuration with namespace.
        env: Environment dict with KUBECONFIG set.

    """
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "get",
            "pods",
            f"--namespace={cfg.namespace}",
            "-o",
            "wide",
        ],
        check=True,
        env=env,
    )


def tail_logs(cfg: Config, env: dict[str, str], *, follow: bool = False) -> None:
    """Stream logs from Ghillie pods.

    Uses kubectl logs to display logs from pods with the app=ghillie label.

    Args:
        cfg: Configuration with namespace.
        env: Environment dict with KUBECONFIG set.
        follow: If True, continuously stream logs (like tail -f).

    """
    cmd = [
        "kubectl",
        "logs",
        "--selector=app.kubernetes.io/name=ghillie",
        f"--namespace={cfg.namespace}",
    ]
    if follow:
        cmd.append("--follow")

    subprocess.run(  # noqa: S603
        cmd,
        check=True,
        env=env,
    )


# =============================================================================
# CLI orchestration helpers
# =============================================================================


def _setup_cnpg(cfg: Config, env: dict[str, str]) -> None:
    """Install CNPG operator and create Postgres cluster."""
    print("Installing CloudNativePG operator...")
    install_cnpg_operator(cfg, env)

    print("Ensuring application namespace exists...")
    ensure_namespace(cfg.namespace, env)

    print("Creating CNPG Postgres cluster...")
    create_cnpg_cluster(cfg, env)

    print("Waiting for Postgres to be ready...")
    wait_for_cnpg_ready(cfg, env)


def _setup_valkey(cfg: Config, env: dict[str, str]) -> None:
    """Install Valkey operator and create instance."""
    print("Installing Valkey operator...")
    install_valkey_operator(cfg, env)

    print("Creating Valkey instance...")
    create_valkey_instance(cfg, env)

    print("Waiting for Valkey to be ready...")
    wait_for_valkey_ready(cfg, env)


def _create_secrets_and_deploy(
    cfg: Config, env: dict[str, str], *, skip_build: bool
) -> None:
    """Read connection URLs, create secrets, and deploy the application."""
    print("Reading connection URLs from secrets...")
    database_url = read_pg_app_uri(cfg, env)
    valkey_url = read_valkey_uri(cfg, env)

    print("Creating application secret...")
    create_app_secret(cfg, env, database_url, valkey_url)

    if not skip_build:
        print(f"Building Docker image {cfg.image_repo}:{cfg.image_tag}...")
        build_docker_image(cfg.image_repo, cfg.image_tag)

        print("Importing image into k3d cluster...")
        import_image_to_k3d(cfg.cluster_name, cfg.image_repo, cfg.image_tag)
    else:
        print("Skipping Docker build (--skip-build)")

    print("Installing Ghillie Helm chart...")
    install_ghillie_chart(cfg, env)


def _print_success_banner(port: int) -> None:
    """Print the success banner with preview URLs and commands."""
    print()
    print("=" * 60)
    print("Preview environment ready!")
    print(f"  URL: http://127.0.0.1:{port}/")
    print(f"  Health check: http://127.0.0.1:{port}/health")
    print()
    print("Commands:")
    print("  Status: uv run scripts/local_k8s.py status")
    print("  Logs:   uv run scripts/local_k8s.py logs --follow")
    print("  Down:   uv run scripts/local_k8s.py down")
    print("=" * 60)


# =============================================================================
# CLI commands
# =============================================================================


@app.command
def up(
    *,
    cluster_name: typ.Annotated[
        str, Parameter(env_var="GHILLIE_K3D_CLUSTER")
    ] = "ghillie-local",
    namespace: typ.Annotated[
        str, Parameter(env_var="GHILLIE_K3D_NAMESPACE")
    ] = "ghillie",
    ingress_port: typ.Annotated[
        int | None, Parameter(env_var="GHILLIE_K3D_PORT")
    ] = None,
    skip_build: bool = False,
) -> int:
    """Create or update the local k3d preview environment.

    Creates a k3d cluster with CloudNativePG and Valkey, builds the Docker
    image, and deploys the Ghillie Helm chart. Safe to run multiple times;
    existing clusters are reused.

    Args:
        cluster_name: Name for the k3d cluster.
        namespace: Kubernetes namespace for Ghillie resources.
        ingress_port: Host port for ingress (auto-selected if not specified).
        skip_build: Skip Docker image build (use existing image).

    Returns:
        Exit code (0 for success, non-zero for failure).

    """
    # Verify required executables
    print("Checking required tools...")
    for exe in ("docker", "k3d", "kubectl", "helm"):
        require_exe(exe)

    # Determine ingress port and build config
    port = ingress_port or pick_free_loopback_port()
    cfg = Config(cluster_name=cluster_name, namespace=namespace, ingress_port=port)

    # Create k3d cluster if needed
    if cluster_exists(cluster_name):
        print(f"Cluster '{cluster_name}' already exists, reusing...")
    else:
        print(f"Creating k3d cluster '{cluster_name}' on port {port}...")
        create_k3d_cluster(cluster_name, port)

    # Set up the Kubernetes environment
    env = kubeconfig_env(cluster_name)

    # Configure infrastructure and deploy
    _setup_cnpg(cfg, env)
    _setup_valkey(cfg, env)
    _create_secrets_and_deploy(cfg, env, skip_build=skip_build)

    _print_success_banner(port)
    return 0


@app.command
def down(
    *,
    cluster_name: typ.Annotated[
        str, Parameter(env_var="GHILLIE_K3D_CLUSTER")
    ] = "ghillie-local",
) -> int:
    """Delete the local k3d cluster.

    Removes the k3d cluster and all associated resources. This operation
    is destructive and cannot be undone.

    Args:
        cluster_name: Name of the k3d cluster to delete.

    Returns:
        Exit code (0 for success, non-zero for failure).

    """
    require_exe("k3d")

    if not cluster_exists(cluster_name):
        print(f"Cluster '{cluster_name}' does not exist.")
        return 0

    print(f"Deleting cluster '{cluster_name}'...")
    delete_k3d_cluster(cluster_name)
    print("Cluster deleted successfully.")
    return 0


@app.command
def status(
    *,
    cluster_name: typ.Annotated[
        str, Parameter(env_var="GHILLIE_K3D_CLUSTER")
    ] = "ghillie-local",
    namespace: typ.Annotated[
        str, Parameter(env_var="GHILLIE_K3D_NAMESPACE")
    ] = "ghillie",
) -> int:
    """Show status of the local preview environment.

    Displays pod status, services, and ingress configuration for the
    Ghillie preview environment.

    Args:
        cluster_name: Name of the k3d cluster.
        namespace: Kubernetes namespace to inspect.

    Returns:
        Exit code (0 for success, non-zero for failure).

    """
    for exe in ("k3d", "kubectl"):
        require_exe(exe)

    if not cluster_exists(cluster_name):
        print(f"Cluster '{cluster_name}' does not exist.")
        return 1

    cfg = Config(cluster_name=cluster_name, namespace=namespace)
    env = kubeconfig_env(cluster_name)

    print(f"Status for cluster: {cluster_name}")
    print(f"Namespace: {namespace}")
    print()
    print_status(cfg, env)
    return 0


@app.command
def logs(
    *,
    cluster_name: typ.Annotated[
        str, Parameter(env_var="GHILLIE_K3D_CLUSTER")
    ] = "ghillie-local",
    namespace: typ.Annotated[
        str, Parameter(env_var="GHILLIE_K3D_NAMESPACE")
    ] = "ghillie",
    follow: bool = False,
) -> int:
    """Tail application logs from the preview environment.

    Streams logs from Ghillie pods in the preview environment.

    Args:
        cluster_name: Name of the k3d cluster.
        namespace: Kubernetes namespace containing Ghillie pods.
        follow: Continuously stream logs (like tail -f).

    Returns:
        Exit code (0 for success, non-zero for failure).

    """
    for exe in ("k3d", "kubectl"):
        require_exe(exe)

    if not cluster_exists(cluster_name):
        print(f"Cluster '{cluster_name}' does not exist.")
        return 1

    cfg = Config(cluster_name=cluster_name, namespace=namespace)
    env = kubeconfig_env(cluster_name)

    tail_logs(cfg, env, follow=follow)
    return 0


def main() -> int:
    """Entry point for the CLI."""
    return app()


if __name__ == "__main__":
    sys.exit(main())
