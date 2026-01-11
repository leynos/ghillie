"""Configuration for the local k3d preview environment."""

from __future__ import annotations

import dataclasses
from pathlib import Path


@dataclasses.dataclass(frozen=True, slots=True)
class Config:
    """Configuration for the local k3d preview environment.

    All paths are relative to the repository root unless absolute.

    Attributes:
        ingress_port: Host port for cluster ingress. When None, a free loopback
            port is auto-selected during cluster creation. For existing clusters,
            the port is discovered from the cluster's port mappings.
        app_secret_name: Kubernetes Secret name for application credentials.
            This contains connection URLs, not passwords directly (S105 false
            positive).

    """

    cluster_name: str = "ghillie-local"
    namespace: str = "ghillie"
    ingress_port: int | None = None
    chart_path: Path = dataclasses.field(default_factory=lambda: Path("charts/ghillie"))
    image_repo: str = "ghillie"
    image_tag: str = "local"
    cnpg_release: str = "cnpg"
    cnpg_namespace: str = "cnpg-system"
    valkey_release: str = "valkey-operator"
    valkey_namespace: str = "valkey-operator-system"
    values_file: Path = dataclasses.field(
        default_factory=lambda: Path("tests/helm/fixtures/values_local.yaml")
    )
    pg_cluster_name: str = "pg-ghillie"
    valkey_name: str = "valkey-ghillie"
    # S105 false positive: This is a Kubernetes Secret resource name, not a
    # hardcoded password. The secret contains connection URLs, not credentials.
    app_secret_name: str = "ghillie"  # noqa: S105


@dataclasses.dataclass(frozen=True, slots=True)
class HelmOperatorSpec:
    """Specification for Helm operator installation.

    Attributes:
        repo_name: Helm repository alias.
        repo_url: Helm repository URL.
        release_name: Helm release name.
        chart_name: Fully qualified chart name (repo/chart).
        namespace: Target namespace for the operator.

    """

    repo_name: str
    repo_url: str
    release_name: str
    chart_name: str
    namespace: str
