"""Kubernetes namespace operations."""

from __future__ import annotations

import subprocess


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
