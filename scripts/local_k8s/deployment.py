"""Docker and Helm deployment operations."""

from __future__ import annotations

import subprocess
import typing as typ

if typ.TYPE_CHECKING:
    from local_k8s.config import Config


def create_app_secret(
    cfg: Config,
    env: dict[str, str],
    database_url: str,
    valkey_url: str,
) -> None:
    """Create the Ghillie application Kubernetes Secret.

    Creates a generic secret containing DATABASE_URL and VALKEY_URL for
    the application to connect to Postgres and Valkey. Uses dry-run + apply
    pattern for idempotent upsert behavior.

    Args:
        cfg: Configuration with namespace and secret name.
        env: Environment dict with KUBECONFIG set.
        database_url: PostgreSQL connection URL from CNPG.
        valkey_url: Valkey connection URL.

    """
    # Generate secret YAML using dry-run
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "create",
            "secret",
            "generic",
            cfg.app_secret_name,
            f"--namespace={cfg.namespace}",
            f"--from-literal=DATABASE_URL={database_url}",
            f"--from-literal=VALKEY_URL={valkey_url}",
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    # Apply for idempotent upsert
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],  # noqa: S607
        input=result.stdout,
        text=True,
        check=True,
        env=env,
    )


def build_docker_image(image_repo: str, image_tag: str) -> None:
    """Build the Docker image locally.

    Builds the Ghillie Docker image from the Dockerfile in the repository root.

    Args:
        image_repo: Repository name for the image.
        image_tag: Tag for the image.

    """
    image_name = f"{image_repo}:{image_tag}"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "docker",
            "build",
            "-t",
            image_name,
            ".",
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

    """
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "helm",
            "upgrade",
            "--install",
            "ghillie",
            str(cfg.chart_path),
            "--namespace",
            cfg.namespace,
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
