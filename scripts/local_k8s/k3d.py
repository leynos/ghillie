"""k3d cluster lifecycle operations.

This module provides functions for managing k3d clusters used in local
Kubernetes development environments. It wraps the k3d CLI to create, delete,
and inspect clusters, manage kubeconfig files, and import Docker images.

All functions that interact with k3d use subprocess calls with appropriate
timeouts and error handling. Port mappings are configured for loopback
(127.0.0.1) to keep clusters accessible only from the local machine.

Public API
----------
- ``get_cluster_ingress_port``: Retrieve the host port mapped to ingress.
- ``cluster_exists``: Check whether a named cluster exists.
- ``create_k3d_cluster``: Create a new k3d cluster with port mapping.
- ``delete_k3d_cluster``: Delete an existing k3d cluster.
- ``write_kubeconfig``: Write and return the kubeconfig path for a cluster.
- ``kubeconfig_env``: Return environment dict with KUBECONFIG set.
- ``import_image_to_k3d``: Import a Docker image into a k3d cluster.

Examples
--------
Check if a cluster exists and create one if not:

    if not cluster_exists("ghillie-local"):
        create_k3d_cluster("ghillie-local", port=8080, agents=1)

Get the kubeconfig environment for kubectl commands:

    env = kubeconfig_env("ghillie-local")
    subprocess.run(["kubectl", "get", "pods"], env=env)

Import a locally built image into the cluster:

    import_image_to_k3d("ghillie-local", "myapp", "latest")

Notes
-----
The module uses non-privileged ports only (1024-65535) for security.
All k3d subprocess calls have configurable timeouts to prevent hangs.

"""

from __future__ import annotations

import json
import os
import subprocess
import typing as typ
from pathlib import Path

from local_k8s._port_utils import _MAX_PORT, _MIN_PORT, _extract_http_host_port

# Default timeout for k3d subprocess operations (seconds)
_K3D_SUBPROCESS_TIMEOUT = 60


def _ensure_valid_host_port(port: int) -> None:
    """Validate a host port is within the allowed range."""
    if not _MIN_PORT <= port <= _MAX_PORT:
        msg = f"port must be between {_MIN_PORT} and {_MAX_PORT}, got {port}"
        raise ValueError(msg)


def _run_k3d_json(args: list[str], *, timeout: float | None = None) -> typ.Any:  # noqa: ANN401
    """Run a k3d command and parse JSON output."""
    try:
        result = subprocess.run(  # noqa: S603
            # k3d is expected on PATH; shell=False mitigates injection
            ["k3d", *args, "-o", "json"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout or _K3D_SUBPROCESS_TIMEOUT,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    else:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None


def _list_clusters() -> list[dict] | None:
    """List all k3d clusters as parsed JSON.

    Returns:
        List of cluster dicts if successful, None on error.

    """
    result = _run_k3d_json(["cluster", "list"])
    if isinstance(result, list):
        return result
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


def get_cluster_ingress_port(cluster_name: str) -> int | None:
    """Get the ingress port for an existing k3d cluster.

    Inspects the k3d cluster's port mappings to find the host port that maps
    to port 80 (HTTP ingress) inside the cluster.

    Parameters
    ----------
    cluster_name : str
        Name of the cluster to inspect.

    Returns
    -------
    int or None
        The host port as an int if found, None otherwise.

    """
    clusters = _run_k3d_json(["cluster", "list"])
    cluster = next(
        (item for item in clusters or [] if item.get("name") == cluster_name),
        None,
    )
    if cluster is None:
        return None

    return _extract_http_host_port(cluster)


def cluster_exists(cluster_name: str) -> bool:
    """Check if a k3d cluster already exists.

    Parameters
    ----------
    cluster_name : str
        Name of the cluster to check for.

    Returns
    -------
    bool
        True if the cluster exists, False otherwise. Returns False if k3d
        is unavailable or returns invalid output.

    """
    clusters = _run_k3d_json(["cluster", "list"])
    return any(cluster.get("name") == cluster_name for cluster in clusters or [])


def create_k3d_cluster(
    cluster_name: str, port: int, agents: int = 1, timeout: float = 300
) -> None:
    """Create a k3d cluster with loopback port mapping.

    Creates a k3d cluster configured with the specified number of agent nodes
    and port mapping from loopback (127.0.0.1) to Traefik on port 80.

    Parameters
    ----------
    cluster_name : str
        Name for the new cluster.
    port : int
        Host port to map to ingress (port 80 on the load balancer). Must be
        in the range 1024-65535 (non-privileged ports).
    agents : int, default 1
        Number of agent nodes. Must be >= 0.
    timeout : float, default 300
        Maximum time in seconds to wait for creation.

    Raises
    ------
    ValueError
        If port is outside the valid range or agents is negative.
    RuntimeError
        If cluster creation times out or fails.

    """
    _ensure_valid_host_port(port)
    if agents < 0:
        msg = f"agents must be >= 0, got {agents}"
        raise ValueError(msg)

    port_mapping = f"127.0.0.1:{port}:80@loadbalancer"
    try:
        subprocess.run(  # noqa: S603
            # k3d is expected on PATH; shell=False mitigates injection
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
    except subprocess.CalledProcessError as e:
        msg = f"k3d cluster creation failed for '{cluster_name}': {e}"
        raise RuntimeError(msg) from e


def delete_k3d_cluster(cluster_name: str, timeout: float = 120) -> None:
    """Delete a k3d cluster.

    Parameters
    ----------
    cluster_name : str
        Name of the cluster to delete.
    timeout : float, default 120
        Maximum time in seconds to wait for deletion.

    Raises
    ------
    RuntimeError
        If cluster deletion fails or times out.

    """
    try:
        subprocess.run(  # noqa: S603
            # k3d is expected on PATH; shell=False mitigates injection
            ["k3d", "cluster", "delete", cluster_name],  # noqa: S607
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        msg = f"k3d cluster deletion timed out after {timeout} seconds"
        raise RuntimeError(msg) from e
    except subprocess.CalledProcessError as e:
        msg = f"k3d cluster deletion failed for '{cluster_name}': {e}"
        raise RuntimeError(msg) from e


def _run_k3d_kubeconfig_write(cluster_name: str, timeout: float) -> str:
    """Run k3d kubeconfig write and return the path string."""
    try:
        result = subprocess.run(  # noqa: S603
            # k3d is expected on PATH; shell=False mitigates injection
            ["k3d", "kubeconfig", "write", cluster_name],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        msg = f"k3d kubeconfig write timed out after {timeout} seconds"
        raise RuntimeError(msg) from e
    except subprocess.CalledProcessError as e:
        msg = f"k3d kubeconfig write failed for '{cluster_name}': {e}"
        raise RuntimeError(msg) from e

    kubeconfig_path = result.stdout.strip()
    if not kubeconfig_path:
        msg = f"k3d returned empty kubeconfig path for cluster '{cluster_name}'"
        raise RuntimeError(msg)

    return kubeconfig_path


def write_kubeconfig(cluster_name: str, timeout: float = 30) -> Path:
    """Write and return the kubeconfig path for a k3d cluster.

    Uses k3d's kubeconfig write command to generate a dedicated kubeconfig
    file for the specified cluster.

    Parameters
    ----------
    cluster_name : str
        Name of the k3d cluster.
    timeout : float, default 30
        Maximum time in seconds to wait.

    Returns
    -------
    Path
        Path to the generated kubeconfig file.

    Raises
    ------
    RuntimeError
        If the kubeconfig path is empty, the file was not created, or the
        operation times out.

    """
    kubeconfig_path = _run_k3d_kubeconfig_write(cluster_name, timeout)
    path = Path(kubeconfig_path)
    if not path.exists():
        msg = f"Kubeconfig file was not created at {kubeconfig_path}"
        raise RuntimeError(msg)

    return path


def kubeconfig_env(cluster_name: str) -> dict[str, str]:
    """Return environment dict with KUBECONFIG set for the cluster.

    Creates a copy of the current environment with KUBECONFIG pointing to
    the cluster's kubeconfig file.

    Parameters
    ----------
    cluster_name : str
        Name of the k3d cluster.

    Returns
    -------
    dict[str, str]
        Environment dictionary with KUBECONFIG set.

    """
    kubeconfig = write_kubeconfig(cluster_name)
    env = dict(os.environ)
    env["KUBECONFIG"] = str(kubeconfig)
    return env


def import_image_to_k3d(
    cluster_name: str, image_repo: str, image_tag: str, timeout: float = 600
) -> None:
    """Import a Docker image into the k3d cluster.

    Uses k3d's image import command to make a locally built image
    available to pods running in the cluster.

    Parameters
    ----------
    cluster_name : str
        Name of the k3d cluster.
    image_repo : str
        Repository name of the image.
    image_tag : str
        Tag of the image.
    timeout : float, default 600
        Maximum time in seconds to wait for import.

    Raises
    ------
    RuntimeError
        If image import fails or times out.

    """
    image_name = f"{image_repo}:{image_tag}"
    try:
        subprocess.run(  # noqa: S603
            # k3d is expected on PATH; shell=False mitigates injection
            [  # noqa: S607
                "k3d",
                "image",
                "import",
                image_name,
                "--cluster",
                cluster_name,
            ],
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        msg = f"k3d image import timed out after {timeout} seconds"
        raise RuntimeError(msg) from e
    except subprocess.CalledProcessError as e:
        msg = f"k3d image import failed for '{image_name}': {e}"
        raise RuntimeError(msg) from e
