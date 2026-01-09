"""Generic Helm operator installation."""

from __future__ import annotations

import subprocess
import typing as typ

from local_k8s.k8s import ensure_namespace

if typ.TYPE_CHECKING:
    from local_k8s.config import HelmOperatorSpec


def install_helm_operator(
    spec: HelmOperatorSpec,
    env: dict[str, str],
) -> None:
    """Install a Helm operator with standard workflow.

    Adds repository, updates, ensures namespace, and installs chart.

    Args:
        spec: Helm operator installation specification.
        env: Environment dict with KUBECONFIG set.

    """
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
    )
    subprocess.run(
        ["helm", "repo", "update"],  # noqa: S607
        check=True,
        env=env,
    )
    ensure_namespace(spec.namespace, env)
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
    )
