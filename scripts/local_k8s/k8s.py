"""Kubernetes namespace and resource operations."""

from __future__ import annotations

import subprocess

from local_k8s.validation import b64decode_k8s_secret_field

# Timeout bounds for kubectl wait operations (in seconds).
_MIN_WAIT_TIMEOUT = 1
_MAX_WAIT_TIMEOUT = 3600


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
    """Create a Kubernetes namespace idempotently.

    Uses dry-run + apply pattern for idempotent upsert behaviour.

    Args:
        namespace: Name of the namespace to create.
        env: Environment dict with KUBECONFIG set.

    """
    # Generate namespace YAML using dry-run
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "create",
            "namespace",
            namespace,
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    # Apply for idempotent upsert
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],  # noqa: S607
        input=result.stdout,
        text=True,
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


def apply_manifest(manifest: str, env: dict[str, str]) -> None:
    """Apply a YAML manifest to the cluster via kubectl.

    Args:
        manifest: YAML manifest string to apply.
        env: Environment dict with KUBECONFIG set.

    """
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],  # noqa: S607
        input=manifest,
        text=True,
        check=True,
        env=env,
    )


def wait_for_pods_ready(
    selector: str, namespace: str, env: dict[str, str], timeout: int = 300
) -> None:
    """Wait for pods matching a label selector to be ready.

    Uses kubectl wait to block until all matching pods are in Ready condition.

    Args:
        selector: Label selector for pods (e.g., "app=myapp").
        namespace: Kubernetes namespace containing the pods.
        env: Environment dict with KUBECONFIG set.
        timeout: Maximum time to wait in seconds (default 300). Must be between
            1 and 3600.

    Raises:
        ValueError: If timeout is outside the valid range (1-3600 seconds).

    """
    if not _MIN_WAIT_TIMEOUT <= timeout <= _MAX_WAIT_TIMEOUT:
        msg = (
            f"timeout must be between {_MIN_WAIT_TIMEOUT} and "
            f"{_MAX_WAIT_TIMEOUT} seconds, got {timeout}"
        )
        raise ValueError(msg)

    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "wait",
            "--for=condition=Ready",
            "pod",
            f"--selector={selector}",
            f"--namespace={namespace}",
            f"--timeout={timeout}s",
        ],
        check=True,
        env=env,
    )


def read_secret_field(
    secret_name: str, field: str, namespace: str, env: dict[str, str]
) -> str:
    """Read and decode a field from a Kubernetes secret.

    Retrieves the specified field from a secret and decodes it from base64.

    Args:
        secret_name: Name of the Kubernetes secret.
        field: Name of the field within the secret's data section.
        namespace: Kubernetes namespace containing the secret.
        env: Environment dict with KUBECONFIG set.

    Returns:
        The decoded UTF-8 string value of the secret field.

    Raises:
        ValueError: If the secret field is empty or missing.

    """
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "get",
            "secret",
            secret_name,
            f"--namespace={namespace}",
            "-o",
            f"jsonpath={{.data.{field}}}",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    if not result.stdout:
        msg = f"Secret '{secret_name}' field '{field}' is empty or missing"
        raise ValueError(msg)

    return b64decode_k8s_secret_field(result.stdout)
