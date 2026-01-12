"""Deployment operations for the local k3d preview environment.

This module wraps the docker, kubectl, and helm calls needed to build the
Ghillie image, create the application secret, and install the chart. It keeps
subprocess usage and input validation in one place so higher-level orchestration
commands stay focused on workflow.

Examples
--------
Build and deploy the application:

    cfg = Config()
    env = kubeconfig_env(cfg.cluster_name)
    create_app_secret(cfg, env, database_url, valkey_url)
    build_docker_image(cfg.image_repo, cfg.image_tag)
    install_ghillie_chart(cfg, env)

"""

from __future__ import annotations

import json
import subprocess
import typing as typ
from pathlib import Path

if typ.TYPE_CHECKING:
    from local_k8s.config import Config

# Timeout for Helm install operations (seconds).
_HELM_INSTALL_TIMEOUT = 600


def create_app_secret(
    cfg: Config,
    env: dict[str, str],
    database_url: str,
    valkey_url: str,
) -> None:
    """Create the Ghillie application Kubernetes Secret.

    Creates a generic secret containing DATABASE_URL and VALKEY_URL for
    the application to connect to Postgres and Valkey. Uses kubectl apply
    with JSON manifest via stdin for idempotent upsert behaviour, avoiding
    exposure of secret values in command-line arguments.

    Args:
        cfg: Configuration with namespace and secret name.
        env: Environment dict with KUBECONFIG set.
        database_url: PostgreSQL connection URL from CNPG.
        valkey_url: Valkey connection URL.

    Raises:
        ValueError: If database_url or valkey_url is empty.

    """
    if not database_url:
        msg = "database_url cannot be empty"
        raise ValueError(msg)
    if not valkey_url:
        msg = "valkey_url cannot be empty"
        raise ValueError(msg)

    # Build secret manifest as JSON to avoid leaking values via command-line
    secret_manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": cfg.app_secret_name,
            "namespace": cfg.namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "local_k8s",
                "app.kubernetes.io/name": cfg.app_name,
                "app.kubernetes.io/instance": cfg.app_name,
            },
        },
        "stringData": {
            "DATABASE_URL": database_url,
            "VALKEY_URL": valkey_url,
        },
    }

    # Apply via stdin for idempotent upsert; shell=False mitigates injection.
    cmd = ["kubectl", "apply", "-f", "-"]
    subprocess.run(  # noqa: S603
        cmd,
        input=json.dumps(secret_manifest),
        text=True,
        check=True,
        env=env,
        timeout=60,
    )


def build_docker_image(
    image_repo: str, image_tag: str, context: Path | str = "."
) -> None:
    """Build the Docker image locally.

    Builds the Ghillie Docker image from the Dockerfile in the repository root.

    Args:
        image_repo: Repository name for the image.
        image_tag: Tag for the image.
        context: Build context directory path. Defaults to current directory.

    Raises:
        FileNotFoundError: If the context path does not exist.
        NotADirectoryError: If the context path is not a directory.
        subprocess.CalledProcessError: If the docker build command fails.

    """
    context_path = Path(context)
    if not context_path.exists():
        msg = f"Build context path does not exist: {context_path}"
        raise FileNotFoundError(msg)
    if not context_path.is_dir():
        msg = f"Build context must be a directory: {context_path}"
        raise NotADirectoryError(msg)

    image_name = f"{image_repo}:{image_tag}"
    # S603/S607: docker via PATH is standard; args are validated inputs
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "docker",
            "build",
            "-t",
            image_name,
            str(context_path),
        ],
        check=True,
        timeout=600,
    )


def install_ghillie_chart(cfg: Config, env: dict[str, str]) -> None:
    """Install the Ghillie Helm chart.

    Uses helm upgrade --install for idempotent installation. The chart is
    installed from the local charts/ghillie directory using the local
    values file.

    Args:
        cfg: Configuration with chart path, namespace, and values file.
        env: Environment dict with KUBECONFIG set.

    Raises:
        FileNotFoundError: If the chart directory or values file does not exist.

    """
    if not cfg.chart_path.exists():
        msg = f"Helm chart not found at {cfg.chart_path}"
        raise FileNotFoundError(msg)
    if not cfg.values_file.exists():
        msg = f"Values file not found at {cfg.values_file}"
        raise FileNotFoundError(msg)

    # S603/S607: helm via PATH is standard; args from validated Config paths
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "helm",
            "upgrade",
            "--install",
            cfg.app_name,
            str(cfg.chart_path),
            "--namespace",
            cfg.namespace,
            "--create-namespace",
            "--values",
            str(cfg.values_file),
            "--set",
            f"image.repository={cfg.image_repo}",
            "--set",
            f"image.tag={cfg.image_tag}",
            "--wait",
            "--timeout",
            f"{_HELM_INSTALL_TIMEOUT}s",
        ],
        check=True,
        env=env,
        timeout=_HELM_INSTALL_TIMEOUT,
    )


def print_status(cfg: Config, env: dict[str, str]) -> None:
    """Print pod status for the preview environment.

    Displays the status of all pods in the configured namespace using
    kubectl get pods.

    Args:
        cfg: Configuration with namespace.
        env: Environment dict with KUBECONFIG set.

    """
    # S603/S607: kubectl via PATH is standard; namespace from Config
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
        timeout=30,
    )


def tail_logs(cfg: Config, env: dict[str, str], *, follow: bool = False) -> None:
    """Stream logs from Ghillie pods.

    Uses kubectl logs to display logs from pods with the configured app label.

    Args:
        cfg: Configuration with namespace.
        env: Environment dict with KUBECONFIG set.
        follow: If True, continuously stream logs (like tail -f). Note that
            follow mode runs indefinitely until interrupted, so no timeout
            is applied.

    """
    cmd = [
        "kubectl",
        "logs",
        f"--selector=app.kubernetes.io/name={cfg.app_name}",
        f"--namespace={cfg.namespace}",
    ]
    if follow:
        cmd.append("--follow")

    # Only apply timeout for non-follow mode; follow runs indefinitely
    timeout = None if follow else 30
    # S603: kubectl via PATH is standard; args from hardcoded flags and Config
    subprocess.run(  # noqa: S603
        cmd,
        check=True,
        env=env,
        timeout=timeout,
    )
