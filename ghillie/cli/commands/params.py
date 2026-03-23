"""Parameter objects for CLI command functions."""

from __future__ import annotations

import dataclasses
import enum
import typing as typ
from pathlib import Path

from cyclopts import Parameter


class ResourceScope(enum.StrEnum):
    """Scope for resource-targeted commands."""

    REPOSITORY = "repository"
    ESTATE = "estate"


class ExportFormat(enum.StrEnum):
    """Export output format."""

    JSON = "json"
    JSONL = "jsonl"
    CSV = "csv"


class ModelBackend(enum.StrEnum):
    """LLM backend provider."""

    MOCK = "mock"
    OPENAI = "openai"


class StackProfile(enum.StrEnum):
    """Stack component profile."""

    API_ONLY = "api-only"
    INGESTION_WORKER = "ingestion-worker"
    REPORTING_WORKER = "reporting-worker"


class RuntimeBackend(enum.StrEnum):
    """Local runtime orchestration backend."""

    CUPRUM = "cuprum"
    PYTHON_API = "python-api"


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

    export_format: typ.Annotated[ExportFormat, Parameter(name="--format")] = (
        ExportFormat.JSON
    )
    output_path: Path = dataclasses.field(default_factory=Path)


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
    model_backend: ModelBackend = ModelBackend.MOCK
    wait: bool = True


@dataclasses.dataclass(frozen=True, slots=True)
class StackRunOptions:
    """Stack lifecycle profile and execution configuration."""

    profile: StackProfile = StackProfile.API_ONLY
    backend: RuntimeBackend = RuntimeBackend.CUPRUM
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
    provider_model_backend: ModelBackend = ModelBackend.MOCK
    provider_openai_key_env: str = "GHILLIE_OPENAI_API_KEY"
