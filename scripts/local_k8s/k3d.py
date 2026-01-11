"""k3d cluster lifecycle operations."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _list_clusters() -> list[dict] | None:
    """List all k3d clusters as parsed JSON.

    Returns:
        List of cluster dicts if successful, None on error.

    """
    try:
        result = subprocess.run(
            ["k3d", "cluster", "list", "-o", "json"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _find_cluster(cluster_name: str) -> dict | None:
    """Find a cluster by name from the list of k3d clusters.

    Args:
        cluster_name: Name of the cluster to find.

    Returns:
        The cluster dict if found, None otherwise.

    """
    clusters = _list_clusters()
    if clusters is None:
        return None

    for cluster in clusters:
        if cluster.get("name") == cluster_name:
            return cluster

    return None


def _is_http_port(container_port: str) -> bool:
    """Check if the container port is HTTP (port 80).

    Args:
        container_port: Container port string (e.g., "80/tcp").

    Returns:
        True if the port is HTTP port 80.

    """
    return container_port.startswith("80/")


def _parse_host_port(host_port_str: str) -> int | None:
    """Parse a host port string to an integer.

    Args:
        host_port_str: Host port string to parse.

    Returns:
        The parsed port number, or None if parsing fails.

    """
    try:
        return int(host_port_str)
    except ValueError:
        return None


def _find_host_port_in_mappings(mappings: list[dict] | None) -> int | None:
    """Find the first valid host port from a list of port mappings.

    Args:
        mappings: List of port mapping dicts with "HostPort" keys.

    Returns:
        The first valid host port, or None if not found.

    """
    for mapping in mappings or []:
        host_port_str = mapping.get("HostPort")
        if host_port_str:
            port = _parse_host_port(host_port_str)
            if port is not None:
                return port
    return None


def _find_http_port_in_node(node: dict) -> int | None:
    """Find HTTP host port in a single node's port mappings.

    Args:
        node: k3d node dict with portMappings.

    Returns:
        Host port mapped to container port 80, or None if not found.

    """
    port_mappings = node.get("portMappings") or {}
    for container_port, mappings in port_mappings.items():
        if _is_http_port(container_port):
            port = _find_host_port_in_mappings(mappings)
            if port is not None:
                return port
    return None


def _extract_http_host_port(cluster: dict) -> int | None:
    """Extract HTTP host port from cluster node port mappings.

    Searches through cluster nodes for port mappings that map container port 80
    to a host port.

    Args:
        cluster: k3d cluster dict from JSON output.

    Returns:
        Host port mapped to container port 80, or None if not found.

    """
    for node in cluster.get("nodes") or []:
        port = _find_http_port_in_node(node)
        if port is not None:
            return port
    return None


def get_cluster_ingress_port(cluster_name: str) -> int | None:
    """Get the ingress port for an existing k3d cluster.

    Inspects the k3d cluster's port mappings to find the host port that maps
    to port 80 (HTTP ingress) inside the cluster.

    Args:
        cluster_name: Name of the cluster to inspect.

    Returns:
        The host port as an int if found, None otherwise.

    """
    cluster = _find_cluster(cluster_name)
    if cluster is None:
        return None

    return _extract_http_host_port(cluster)


def cluster_exists(cluster_name: str) -> bool:
    """Check if a k3d cluster already exists.

    Args:
        cluster_name: Name of the cluster to check for.

    Returns:
        True if the cluster exists, False otherwise. Returns False if k3d
        is unavailable or returns invalid output.

    """
    return _find_cluster(cluster_name) is not None


_MIN_PORT = 1024
_MAX_PORT = 65535


def create_k3d_cluster(
    cluster_name: str, port: int, agents: int = 1, timeout: float = 300
) -> None:
    """Create a k3d cluster with loopback port mapping.

    Creates a k3d cluster configured with:
    - Specified number of agent nodes
    - Port mapping from loopback (127.0.0.1) to Traefik on port 80

    Args:
        cluster_name: Name for the new cluster.
        port: Host port to map to ingress (port 80 on the load balancer). Must
            be in the range 1024-65535 (non-privileged ports).
        agents: Number of agent nodes (default 1).
        timeout: Maximum time in seconds to wait for creation (default 300).

    Raises:
        ValueError: If port is outside the valid range.
        RuntimeError: If cluster creation times out.

    """
    if not _MIN_PORT <= port <= _MAX_PORT:
        msg = f"port must be between {_MIN_PORT} and {_MAX_PORT}, got {port}"
        raise ValueError(msg)

    port_mapping = f"127.0.0.1:{port}:80@loadbalancer"
    try:
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
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        msg = f"k3d cluster creation timed out after {timeout} seconds"
        raise RuntimeError(msg) from e


def delete_k3d_cluster(cluster_name: str, timeout: float = 120) -> None:
    """Delete a k3d cluster.

    Args:
        cluster_name: Name of the cluster to delete.
        timeout: Maximum time in seconds to wait for deletion (default 120).

    """
    subprocess.run(  # noqa: S603
        ["k3d", "cluster", "delete", cluster_name],  # noqa: S607
        check=True,
        timeout=timeout,
    )


def write_kubeconfig(cluster_name: str) -> Path:
    """Write and return the kubeconfig path for a k3d cluster.

    Uses k3d's kubeconfig write command to generate a dedicated kubeconfig
    file for the specified cluster.

    Args:
        cluster_name: Name of the k3d cluster.

    Returns:
        Path to the generated kubeconfig file.

    Raises:
        RuntimeError: If the kubeconfig path is empty or the file was not
            created.

    """
    result = subprocess.run(  # noqa: S603
        ["k3d", "kubeconfig", "write", cluster_name],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    kubeconfig_path = result.stdout.strip()
    if not kubeconfig_path:
        msg = f"k3d returned empty kubeconfig path for cluster '{cluster_name}'"
        raise RuntimeError(msg)

    path = Path(kubeconfig_path)
    if not path.exists():
        msg = f"Kubeconfig file was not created at {kubeconfig_path}"
        raise RuntimeError(msg)

    return path


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
