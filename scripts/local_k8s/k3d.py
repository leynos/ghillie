"""k3d cluster lifecycle operations."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


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
