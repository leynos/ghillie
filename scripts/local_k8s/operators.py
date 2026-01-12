"""Generic Helm operator installation."""

from __future__ import annotations

import subprocess
import typing as typ

from local_k8s.k8s import ensure_namespace

if typ.TYPE_CHECKING:
    from local_k8s.config import HelmOperatorSpec

# Timeouts for Helm operations (in seconds).
_HELM_REPO_TIMEOUT = 60
_HELM_INSTALL_TIMEOUT = 300


def install_helm_operator(
    spec: HelmOperatorSpec,
    env: dict[str, str],
) -> None:
    """Install a Helm operator with standard workflow.

    Adds repository, updates, ensures namespace, and installs chart.

    Args:
        spec: Helm operator installation specification.
        env: Environment dict with KUBECONFIG set.

    Raises:
        RuntimeError: If any Helm operation fails.

    """
    # S603/S607: helm via PATH is standard; args from validated HelmOperatorSpec
    try:
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "helm",
                "repo",
                "add",
                "--force-update",
                spec.repo_name,
                spec.repo_url,
            ],
            check=True,
            env=env,
            timeout=_HELM_REPO_TIMEOUT,
        )
    except subprocess.CalledProcessError as e:
        msg = f"Failed to add Helm repo '{spec.repo_name}': {e}"
        raise RuntimeError(msg) from e

    # Helm via PATH is standard; no user input.
    try:
        cmd = ["helm", "repo", "update"]
        subprocess.run(  # noqa: S603
            cmd,
            check=True,
            env=env,
            timeout=_HELM_REPO_TIMEOUT,
        )
    except subprocess.CalledProcessError as e:
        msg = f"Failed to update Helm repositories: {e}"
        raise RuntimeError(msg) from e

    ensure_namespace(spec.namespace, env)
    # S603/S607: helm via PATH is standard; args from validated HelmOperatorSpec
    try:
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "helm",
                "upgrade",
                "--install",
                spec.release_name,
                spec.chart_name,
                "--namespace",
                spec.namespace,
                "--wait",
            ],
            check=True,
            env=env,
            timeout=_HELM_INSTALL_TIMEOUT,
        )
    except subprocess.CalledProcessError as e:
        msg = f"Failed to install Helm chart '{spec.chart_name}': {e}"
        raise RuntimeError(msg) from e
