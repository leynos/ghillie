"""Docker and Helm deployment operations."""

from __future__ import annotations

import json
import subprocess
import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path

    from local_k8s.config import Config


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
        },
        "stringData": {
            "DATABASE_URL": database_url,
            "VALKEY_URL": valkey_url,
        },
    }

    # Apply via stdin for idempotent upsert
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],  # noqa: S607
        input=json.dumps(secret_manifest),
        text=True,
        check=True,
        env=env,
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

    """
    image_name = f"{image_repo}:{image_tag}"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "docker",
            "build",
            "-t",
            image_name,
            str(context),
        ],
        check=True,
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

    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "helm",
            "upgrade",
            "--install",
            "ghillie",
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
        ],
        check=True,
        env=env,
    )


def print_status(cfg: Config, env: dict[str, str]) -> None:
    """Print pod status for the preview environment.

    Displays the status of all pods in the configured namespace using
    kubectl get pods.

    Args:
        cfg: Configuration with namespace.
        env: Environment dict with KUBECONFIG set.

    """
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
    )


def tail_logs(cfg: Config, env: dict[str, str], *, follow: bool = False) -> None:
    """Stream logs from Ghillie pods.

    Uses kubectl logs to display logs from pods with the app=ghillie label.

    Args:
        cfg: Configuration with namespace.
        env: Environment dict with KUBECONFIG set.
        follow: If True, continuously stream logs (like tail -f).

    """
    cmd = [
        "kubectl",
        "logs",
        "--selector=app.kubernetes.io/name=ghillie",
        f"--namespace={cfg.namespace}",
    ]
    if follow:
        cmd.append("--follow")

    subprocess.run(  # noqa: S603
        cmd,
        check=True,
        env=env,
    )
