"""Parameter objects for CLI command functions."""

from __future__ import annotations

import dataclasses
import typing as typ

from cyclopts import Parameter

ResourceScope = typ.Literal["repository", "estate"]
ExportFormat = typ.Literal["json", "jsonl", "csv"]
ModelBackend = typ.Literal["mock", "openai"]
StackProfile = typ.Literal["api-only", "ingestion-worker", "reporting-worker"]
RuntimeBackend = typ.Literal["cuprum", "python-api"]


@dataclasses.dataclass(frozen=True, slots=True)
class ResourceTarget:
    """Scope and identity for resource-targeted commands."""

    scope: ResourceScope
    estate_key: str | None = None
    owner: str | None = None
    name: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class WindowOptions:
    """Time window configuration for data export and reporting."""

    window_days: int | None = 14
    window_start: str | None = None
    window_end: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class ExportSinkOptions:
    """Export output format and destination configuration."""

    export_format: typ.Annotated[ExportFormat, Parameter(name="--format")] = "json"
    output_path: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class PaginationFilter:
    """Pagination and active/inactive filter configuration."""

    active: bool = True
    inactive: bool = False
    limit: int = 50
    offset: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class NiceMetricsOptions:
    """Optional metrics inclusion flags."""

    include_comments: bool = False
    include_commit_counts: bool = False
    include_sloc_breakdown: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class ReportRunOptions:
    """Report execution configuration."""

    as_of: str | None = None
    model_backend: ModelBackend = "mock"
    wait: bool = True


@dataclasses.dataclass(frozen=True, slots=True)
class StackRunOptions:
    """Stack lifecycle profile and execution configuration."""

    profile: StackProfile = "api-only"
    backend: RuntimeBackend = "cuprum"
    background_workers: bool = False
    wait: bool = True


@dataclasses.dataclass(frozen=True, slots=True)
class ClusterOptions:
    """Cluster identity and image configuration."""

    cluster_name: typ.Annotated[str, Parameter(env_var="GHILLIE_CLUSTER_NAME")] = (
        "ghillie-local"
    )
    namespace: typ.Annotated[str, Parameter(env_var="GHILLIE_NAMESPACE")] = "ghillie"
    ingress_port: typ.Annotated[
        int | None, Parameter(env_var="GHILLIE_INGRESS_PORT")
    ] = None
    image: typ.Annotated[str, Parameter(env_var="GHILLIE_IMAGE")] = "ghillie:local"


@dataclasses.dataclass(frozen=True, slots=True)
class ProviderOptions:
    """External provider credential and backend configuration."""

    provider_github_token_env: str = "GHILLIE_GITHUB_TOKEN"  # noqa: S105
    provider_model_backend: ModelBackend = "mock"
    provider_openai_key_env: str = "GHILLIE_OPENAI_API_KEY"
