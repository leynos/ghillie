"""Kubernetes namespace and resource operations.

This module provides functions for managing Kubernetes namespaces, applying
manifests, waiting for pod readiness, and reading secret fields. All functions
require an environment dictionary with KUBECONFIG set to target the correct
cluster.

Examples
--------
Ensure a namespace exists before deploying resources:

    env = kubeconfig_env("my-cluster")
    ensure_namespace("my-app", env)

Wait for pods to become ready after deployment:

    wait_for_pods_ready("app=my-app", "my-app", env, timeout=120)

Read a database connection URI from a secret:

    db_uri = read_secret_field("db-credentials", "uri", "my-app", env)

"""

from __future__ import annotations

import re
import subprocess

from local_k8s.validation import b64decode_k8s_secret_field

# Kubernetes secret keys must contain only alphanumeric, dot, underscore, or hyphen
_SECRET_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

# Timeout bounds for kubectl wait operations (in seconds).
_MIN_WAIT_TIMEOUT = 1
_MAX_WAIT_TIMEOUT = 3600


def namespace_exists(namespace: str, env: dict[str, str]) -> bool:
    """Check if a Kubernetes namespace exists.

    Parameters
    ----------
    namespace : str
        Name of the namespace to check.
    env : dict[str, str]
        Environment dict with KUBECONFIG set.

    Returns
    -------
    bool
        True if the namespace exists, False otherwise.

    """
    # S603/S607: kubectl via PATH is standard; namespace is validated by k8s API
    result = subprocess.run(  # noqa: S603
        ["kubectl", "get", "namespace", namespace],  # noqa: S607
        capture_output=True,
        env=env,
        timeout=30,
    )
    return result.returncode == 0


def create_namespace(namespace: str, env: dict[str, str]) -> None:
    """Create a Kubernetes namespace idempotently.

    Uses dry-run + apply pattern for idempotent upsert behaviour.

    Parameters
    ----------
    namespace : str
        Name of the namespace to create.
    env : dict[str, str]
        Environment dict with KUBECONFIG set.

    """
    # Generate namespace YAML using dry-run
    # S603/S607: kubectl via PATH is standard; namespace validated by k8s API
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
        timeout=30,
    )
    # Apply for idempotent upsert
    # S607: kubectl via PATH is standard; no user input
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],  # noqa: S607
        input=result.stdout,
        text=True,
        check=True,
        env=env,
        timeout=30,
    )


def ensure_namespace(namespace: str, env: dict[str, str]) -> None:
    """Ensure a Kubernetes namespace exists, creating if necessary.

    Parameters
    ----------
    namespace : str
        Name of the namespace to ensure.
    env : dict[str, str]
        Environment dict with KUBECONFIG set.

    """
    if not namespace_exists(namespace, env):
        create_namespace(namespace, env)


def apply_manifest(manifest: str, env: dict[str, str]) -> None:
    """Apply a YAML manifest to the cluster via kubectl.

    Parameters
    ----------
    manifest : str
        YAML manifest string to apply.
    env : dict[str, str]
        Environment dict with KUBECONFIG set.

    """
    # S607: kubectl via PATH is standard; manifest generated internally
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],  # noqa: S607
        input=manifest,
        text=True,
        check=True,
        env=env,
        timeout=60,
    )


def wait_for_pods_ready(
    selector: str, namespace: str, env: dict[str, str], timeout: int = 300
) -> None:
    """Wait for pods matching a label selector to be ready.

    Uses kubectl wait to block until all matching pods are in Ready condition.

    Parameters
    ----------
    selector : str
        Label selector for pods (e.g., "app=myapp").
    namespace : str
        Kubernetes namespace containing the pods.
    env : dict[str, str]
        Environment dict with KUBECONFIG set.
    timeout : int, default 300
        Maximum time to wait in seconds. Must be between 1 and 3600.

    Raises
    ------
    ValueError
        If timeout is outside the valid range (1-3600 seconds).

    """
    if not _MIN_WAIT_TIMEOUT <= timeout <= _MAX_WAIT_TIMEOUT:
        msg = (
            f"timeout must be between {_MIN_WAIT_TIMEOUT} and "
            f"{_MAX_WAIT_TIMEOUT} seconds, got {timeout}"
        )
        raise ValueError(msg)

    # Add buffer to subprocess timeout beyond kubectl's --timeout
    # S603/S607: kubectl via PATH is standard; selector/namespace from Config
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
        timeout=timeout + 30,
    )


def read_secret_field(
    secret_name: str, field: str, namespace: str, env: dict[str, str]
) -> str:
    """Read and decode a field from a Kubernetes secret.

    Retrieves the specified field from a secret and decodes it from base64.
    Handles dotted field names (e.g., "ca.crt") correctly via quoted jsonpath.

    Parameters
    ----------
    secret_name : str
        Name of the Kubernetes secret.
    field : str
        Name of the field within the secret's data section. Must not be empty
        or contain characters that break jsonpath syntax.
    namespace : str
        Kubernetes namespace containing the secret.
    env : dict[str, str]
        Environment dict with KUBECONFIG set.

    Returns
    -------
    str
        The decoded UTF-8 string value of the secret field.

    Raises
    ------
    ValueError
        If field is empty, contains invalid characters, or the secret field
        value is empty or missing.

    """
    if not field:
        msg = "field cannot be empty"
        raise ValueError(msg)
    # Enforce Kubernetes secret key character rules
    if not _SECRET_KEY_PATTERN.match(field):
        msg = (
            f"field '{field}' contains invalid characters; "
            "only alphanumeric, dot, underscore, and hyphen are allowed"
        )
        raise ValueError(msg)

    # Quote the field name to support dotted keys like "ca.crt"
    jsonpath = f"jsonpath={{.data['{field}']}}"

    # S603/S607: kubectl via PATH is standard; args from Config or hardcoded
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "kubectl",
            "get",
            "secret",
            secret_name,
            f"--namespace={namespace}",
            "-o",
            jsonpath,
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        timeout=30,
    )

    output = result.stdout.strip()
    if not output:
        msg = (
            f"Secret '{secret_name}' field '{field}' is empty or missing "
            f"in namespace '{namespace}'"
        )
        raise ValueError(msg)

    return b64decode_k8s_secret_field(output)
