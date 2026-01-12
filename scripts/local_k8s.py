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

import subprocess
import sys
import typing as typ

from cyclopts import App, Parameter
from local_k8s.orchestration import (
    setup_environment,
    show_environment_status,
    stream_environment_logs,
    teardown_environment,
)
from local_k8s.validation import LocalK8sError

_K3D_CREATE_CMD = ("k3d", "cluster", "create")


def _handle_subprocess_error(e: subprocess.CalledProcessError) -> int:
    """Handle subprocess errors with context-specific messages.

    Args:
        e: The CalledProcessError exception.

    Returns:
        Exit code 1.

    """
    cmd = e.cmd if isinstance(e.cmd, list) else [e.cmd]
    # Check if this was a k3d cluster create failure (likely port in use)
    if tuple(cmd[: len(_K3D_CREATE_CMD)]) == _K3D_CREATE_CMD:
        print(
            "Error: Failed to create k3d cluster. The ingress port may be in use.\n"
            "Try one of the following:\n"
            "  - Let the tool auto-select a port: unset GHILLIE_K3D_PORT\n"
            "  - Choose a different port: export GHILLIE_K3D_PORT=<port>",
            file=sys.stderr,
        )
    else:
        print(f"Error: Command failed: {' '.join(cmd)}", file=sys.stderr)
    return 1


def _run_with_cli_error_handling(action: typ.Callable[[], int]) -> int:
    """Run a CLI action with consistent error handling."""
    try:
        return action()
    except LocalK8sError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        return _handle_subprocess_error(e)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


app = App(
    name="local_k8s",
    help="Local k3d preview environment for Ghillie",
    version="0.1.0",
)


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
    return _run_with_cli_error_handling(
        lambda: setup_environment(
            cluster_name, namespace, ingress_port, skip_build=skip_build
        )
    )


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
    return _run_with_cli_error_handling(lambda: teardown_environment(cluster_name))


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
    return _run_with_cli_error_handling(
        lambda: show_environment_status(cluster_name, namespace)
    )


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
    return _run_with_cli_error_handling(
        lambda: stream_environment_logs(cluster_name, namespace, follow=follow)
    )


def main() -> int:
    """Entry point for the CLI."""
    result = app()
    return result if result is not None else 0


if __name__ == "__main__":
    sys.exit(main())
