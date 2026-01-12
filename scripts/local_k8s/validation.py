"""Validation and utility helpers for local k3d environment setup.

This module provides foundational utilities used across the local_k8s package
for executable verification, port allocation, and secret decoding. It also
defines custom exceptions for error handling throughout the package.

Utilities
---------
- ``require_exe``: Verifies CLI tools (k3d, kubectl, helm, docker) are available
- ``pick_free_loopback_port``: Allocates ephemeral ports for ingress mapping
- ``b64decode_k8s_secret_field``: Decodes base64-encoded Kubernetes secret values

Custom Exceptions
-----------------
- ``LocalK8sError``: Base exception for all package errors
- ``ExecutableNotFoundError``: Raised when a required CLI tool is missing
- ``SecretDecodeError``: Raised when secret decoding fails
- ``PortMismatchError``: Raised when requested port conflicts with existing cluster

These utilities are consumed by the orchestration, k3d, k8s, deployment, cnpg,
and valkey modules throughout the package.

Examples
--------
Verify required executables before proceeding:

    require_exe("k3d")
    require_exe("kubectl")

Allocate a free port for cluster ingress:

    port = pick_free_loopback_port()
    print(f"Using port {port} for ingress")

Decode a secret value retrieved from Kubernetes:

    encoded = "cG9zdGdyZXM6Ly91c2VyOnBhc3NAaG9zdC9kYg=="
    db_uri = b64decode_k8s_secret_field(encoded)

"""

from __future__ import annotations

import base64
import shutil
import socket


class LocalK8sError(Exception):
    """Base exception for all local_k8s package errors."""


class ExecutableNotFoundError(LocalK8sError):
    """Required CLI tool is not installed."""


def require_exe(name: str) -> None:
    """Verify a CLI tool is available in PATH.

    Parameters
    ----------
    name : str
        Name of the executable to check for.

    Raises
    ------
    ExecutableNotFoundError
        If the executable is not found in PATH.

    """
    if shutil.which(name) is None:
        msg = f"Required executable '{name}' not found in PATH"
        raise ExecutableNotFoundError(msg)


def pick_free_loopback_port() -> int:
    """Find an available TCP port on 127.0.0.1.

    Uses the kernel's ephemeral port allocation by binding to port 0,
    which causes the OS to assign an available port.

    Returns
    -------
    int
        An available port number on the loopback interface.

    Notes
    -----
    There is an inherent TOCTOU (time-of-check-time-of-use) race condition
    between this function returning and the caller binding to the port.
    Another process could claim the port in that brief interval. This is
    extremely unlikely in practice for local development, but callers
    should handle subprocess errors from k3d/Docker if port binding fails.

    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class SecretDecodeError(LocalK8sError):
    """Failed to decode a Kubernetes secret field."""


class PortMismatchError(LocalK8sError):
    """Requested port does not match existing cluster's port."""


def b64decode_k8s_secret_field(b64_text: str) -> str:
    """Decode a base64-encoded Kubernetes secret value.

    Kubernetes secrets store values as base64-encoded strings. This function
    decodes them to UTF-8 text.

    Parameters
    ----------
    b64_text : str
        Base64-encoded string from a Kubernetes secret.

    Returns
    -------
    str
        The decoded UTF-8 string.

    Raises
    ------
    SecretDecodeError
        If the input is not valid base64 or cannot be decoded as UTF-8 text.

    """
    try:
        return base64.b64decode(b64_text).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as e:
        msg = f"Failed to decode secret field: {e}"
        raise SecretDecodeError(msg) from e
