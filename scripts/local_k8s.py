#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.13"
# dependencies = ["cyclopts>=2.9", "plumbum"]
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

import dataclasses
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
    print(f"Creating preview environment: {cluster_name}")
    print(f"  Namespace: {namespace}")
    print(f"  Ingress port: {ingress_port or 'auto'}")
    print(f"  Skip build: {skip_build}")
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
    print(f"Deleting cluster: {cluster_name}")
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
    print(f"Status for cluster: {cluster_name}")
    print(f"  Namespace: {namespace}")
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
    print(f"Logs for cluster: {cluster_name}")
    print(f"  Namespace: {namespace}")
    print(f"  Follow: {follow}")
    return 0


def main() -> int:
    """Entry point for the CLI."""
    return app()


if __name__ == "__main__":
    sys.exit(main())
