"""msgspec request and response structs for the estate HTTP boundary.

Request structs reject unknown fields and constrain string lengths so a
malformed body becomes one predictable :class:`msgspec.DecodeError` rather
than a partially populated command. Response structs mirror the documented
envelope; the resources serialize them with :func:`msgspec.to_builtins`.
"""

import datetime as dt  # noqa: TC003 - msgspec resolves Struct fields at runtime.
import typing as typ

import msgspec

MAX_COMMIT_SHA_LENGTH = 64
MAX_ESTATE_NAME_LENGTH = 255

_CommitSha = typ.Annotated[
    str, msgspec.Meta(min_length=1, max_length=MAX_COMMIT_SHA_LENGTH)
]
_EstateName = typ.Annotated[
    str, msgspec.Meta(min_length=1, max_length=MAX_ESTATE_NAME_LENGTH)
]


class ImportCatalogueRequest(msgspec.Struct, forbid_unknown_fields=True):
    """Body of ``POST /estates/{estate_key}/catalogue-import``."""

    commit_sha: _CommitSha
    catalogue_yaml: str
    estate_name: _EstateName | None = None


class IngestionRequest(msgspec.Struct, forbid_unknown_fields=True):
    """Body of ``PATCH /repositories/{owner}/{name}/ingestion``."""

    ingestion_enabled: bool


class CountResponse(msgspec.Struct):
    """Created, updated, and deleted counts for one record family."""

    created: int
    updated: int
    deleted: int


class LastImportResponse(msgspec.Struct):
    """The most recent successful catalogue import for an estate."""

    commit_sha: str
    imported_at: dt.datetime


class EstateSummaryResponse(msgspec.Struct):
    """One estate in ``GET /estates``."""

    key: str
    name: str
    description: str | None
    last_import: LastImportResponse | None


class EstateListResponse(msgspec.Struct):
    """Paginated envelope for ``GET /estates``."""

    items: list[EstateSummaryResponse]
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None


class CatalogueImportResponse(msgspec.Struct):
    """Response body for a catalogue import."""

    estate_key: str
    commit_sha: str
    state: str
    dry_run: bool
    skipped: bool
    skipped_reason: str | None
    registry_sync_required: bool
    projects: CountResponse
    components: CountResponse
    repositories: CountResponse
    edges: CountResponse


class RegistrySyncResponse(msgspec.Struct):
    """Response body for a registry sync."""

    estate_key: str
    state: str
    dry_run: bool
    repositories_created: int
    repositories_updated: int
    repositories_deactivated: int
    repositories_conflicted: list[str]
    repositories_left_disabled: list[str]
    repositories_left_disabled_count: int


class RepositoryResponse(msgspec.Struct):
    """One registered repository in the estate listing."""

    owner: str
    name: str
    default_branch: str
    ingestion_enabled: bool
    documentation_paths: list[str]


class RepositoryListResponse(msgspec.Struct):
    """Paginated envelope for ``GET /estates/{estate_key}/repositories``."""

    estate_key: str
    items: list[RepositoryResponse]
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None


class IngestionToggleResponse(msgspec.Struct):
    """Response body for an ingestion toggle."""

    owner: str
    name: str
    ingestion_enabled: bool
    changed: bool
