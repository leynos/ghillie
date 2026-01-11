"""High-level orchestration for CLI commands."""

from __future__ import annotations

from local_k8s.cnpg import (
    create_cnpg_cluster,
    install_cnpg_operator,
    read_pg_app_uri,
    wait_for_cnpg_ready,
)
from local_k8s.config import Config
from local_k8s.deployment import (
    build_docker_image,
    create_app_secret,
    install_ghillie_chart,
    print_status,
    tail_logs,
)
from local_k8s.k3d import (
    cluster_exists,
    create_k3d_cluster,
    delete_k3d_cluster,
    get_cluster_ingress_port,
    import_image_to_k3d,
    kubeconfig_env,
)
from local_k8s.k8s import ensure_namespace
from local_k8s.validation import (
    PortMismatchError,
    pick_free_loopback_port,
    require_exe,
)
from local_k8s.valkey import (
    create_valkey_instance,
    install_valkey_operator,
    read_valkey_uri,
    wait_for_valkey_ready,
)


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
    print("  Status: make local-k8s-status")
    print("  Logs:   make local-k8s-logs")
    print("  Down:   make local-k8s-down")
    print("=" * 60)


def _validate_and_setup_environment(
    cluster_name: str, namespace: str
) -> tuple[Config, dict[str, str]] | None:
    """Validate cluster exists and return config and environment.

    Args:
        cluster_name: Name of the k3d cluster.
        namespace: Kubernetes namespace.

    Returns:
        Tuple of (Config, environment dict) if cluster exists, None otherwise.

    """
    for exe in ("k3d", "kubectl"):
        require_exe(exe)

    if not cluster_exists(cluster_name):
        print(f"Cluster '{cluster_name}' does not exist.")
        return None

    cfg = Config(cluster_name=cluster_name, namespace=namespace)
    env = kubeconfig_env(cluster_name)
    return cfg, env


def _ensure_cluster_ready(
    cluster_name: str, ingress_port: int | None
) -> tuple[int, bool]:
    """Ensure k3d cluster exists and determine the ingress port.

    Args:
        cluster_name: Name for the k3d cluster.
        ingress_port: Requested host port for ingress (auto-selected if None).

    Returns:
        Tuple of (port to use, whether this is a new cluster).

    Raises:
        PortMismatchError: If there's a port mismatch with an existing cluster.

    """
    port = ingress_port or pick_free_loopback_port()

    if cluster_exists(cluster_name):
        print(f"Cluster '{cluster_name}' already exists, reusing...")

        existing_port = get_cluster_ingress_port(cluster_name)

        if existing_port is None:
            print(
                f"Warning: Could not determine ingress port for cluster "
                f"'{cluster_name}'. Assuming port {port}."
            )
        elif ingress_port is not None and ingress_port != existing_port:
            msg = (
                f"Ingress port mismatch: existing cluster '{cluster_name}' uses "
                f"port {existing_port}, but --ingress-port={ingress_port} was "
                f"requested. Either re-run without --ingress-port to reuse port "
                f"{existing_port}, or delete the cluster first with "
                f"'make local-k8s-down'."
            )
            raise PortMismatchError(msg)
        else:
            port = existing_port

        return port, False

    print(f"Creating k3d cluster '{cluster_name}' on port {port}...")
    create_k3d_cluster(cluster_name, port)
    return port, True


def setup_environment(
    cluster_name: str,
    namespace: str,
    ingress_port: int | None,
    *,
    skip_build: bool,
) -> int:
    """Create and configure the entire preview environment.

    Args:
        cluster_name: Name for the k3d cluster.
        namespace: Kubernetes namespace for Ghillie resources.
        ingress_port: Host port for ingress (auto-selected if not specified).
        skip_build: Skip Docker image build (use existing image).

    Returns:
        Exit code (0 for success, non-zero for failure).

    """
    # Verify required executables (docker only needed for builds)
    print("Checking required tools...")
    required_tools = ["k3d", "kubectl", "helm"]
    if not skip_build:
        required_tools.insert(0, "docker")
    for exe in required_tools:
        require_exe(exe)

    # Ensure cluster exists and determine port
    port, _is_new = _ensure_cluster_ready(cluster_name, ingress_port)

    cfg = Config(cluster_name=cluster_name, namespace=namespace, ingress_port=port)
    env = kubeconfig_env(cluster_name)

    # Configure infrastructure and deploy
    _setup_cnpg(cfg, env)
    _setup_valkey(cfg, env)
    _create_secrets_and_deploy(cfg, env, skip_build=skip_build)

    _print_success_banner(port)
    return 0


def teardown_environment(cluster_name: str) -> int:
    """Delete the k3d cluster and all resources.

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


def show_environment_status(cluster_name: str, namespace: str) -> int:
    """Display the status of the preview environment.

    Args:
        cluster_name: Name of the k3d cluster.
        namespace: Kubernetes namespace to inspect.

    Returns:
        Exit code (0 for success, 1 if cluster doesn't exist).

    """
    result = _validate_and_setup_environment(cluster_name, namespace)
    if result is None:
        return 1

    cfg, env = result

    print(f"Status for cluster: {cluster_name}")
    print(f"Namespace: {namespace}")
    print()
    print_status(cfg, env)
    return 0


def stream_environment_logs(cluster_name: str, namespace: str, *, follow: bool) -> int:
    """Stream application logs from the preview environment.

    Args:
        cluster_name: Name of the k3d cluster.
        namespace: Kubernetes namespace containing Ghillie pods.
        follow: Continuously stream logs (like tail -f).

    Returns:
        Exit code (0 for success, 1 if cluster doesn't exist).

    """
    result = _validate_and_setup_environment(cluster_name, namespace)
    if result is None:
        return 1

    cfg, env = result

    tail_logs(cfg, env, follow=follow)
    return 0
