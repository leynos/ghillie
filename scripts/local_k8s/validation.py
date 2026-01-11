"""Validation and utility helpers."""

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

    Args:
        name: Name of the executable to check for.

    Raises:
        ExecutableNotFoundError: If the executable is not found in PATH.

    """
    if shutil.which(name) is None:
        msg = f"Required executable '{name}' not found in PATH"
        raise ExecutableNotFoundError(msg)


def pick_free_loopback_port() -> int:
    """Find an available TCP port on 127.0.0.1.

    Uses the kernel's ephemeral port allocation by binding to port 0,
    which causes the OS to assign an available port.

    Note:
        There is an inherent TOCTOU (time-of-check-time-of-use) race condition
        between this function returning and the caller binding to the port.
        Another process could claim the port in that brief interval. This is
        extremely unlikely in practice for local development, but callers
        should handle subprocess errors from k3d/Docker if port binding fails.

    Returns:
        An available port number on the loopback interface.

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

    Args:
        b64_text: Base64-encoded string from a Kubernetes secret.

    Returns:
        The decoded UTF-8 string.

    Raises:
        SecretDecodeError: If the input is not valid base64 or cannot be
            decoded as UTF-8 text.

    """
    try:
        return base64.b64decode(b64_text).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as e:
        msg = f"Failed to decode secret field: {e}"
        raise SecretDecodeError(msg) from e
