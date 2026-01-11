"""Local k3d preview environment management package.

This package provides a programmatic interface to manage local k3d preview
environments for Ghillie. The primary entrypoints are:

- setup_environment: Create and configure a local k3d preview environment
- teardown_environment: Delete a local k3d preview environment
- show_environment_status: Display pod status for a preview environment
- stream_environment_logs: Stream logs from Ghillie pods

For lower-level operations, import directly from submodules:

- local_k8s.k3d: k3d cluster lifecycle operations
- local_k8s.k8s: Kubernetes namespace and resource operations
- local_k8s.cnpg: CloudNativePG operations
- local_k8s.valkey: Valkey operations
- local_k8s.deployment: Docker and Helm deployment operations
- local_k8s.validation: Validation and utility helpers

"""

from __future__ import annotations

from local_k8s.config import Config, HelmOperatorSpec
from local_k8s.orchestration import (
    setup_environment,
    show_environment_status,
    stream_environment_logs,
    teardown_environment,
)
from local_k8s.validation import (
    ExecutableNotFoundError,
    LocalK8sError,
    PortMismatchError,
    SecretDecodeError,
)

# Public API: only stable exports for external consumers
# Helpers remain importable via their submodules (e.g., local_k8s.k3d.cluster_exists)
__all__ = [
    "Config",
    "ExecutableNotFoundError",
    "HelmOperatorSpec",
    "LocalK8sError",
    "PortMismatchError",
    "SecretDecodeError",
    "setup_environment",
    "show_environment_status",
    "stream_environment_logs",
    "teardown_environment",
]
