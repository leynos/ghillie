"""Falcon resources for the estate-management endpoints (D1, D5, D6, D8).

The resources translate HTTP into calls on
:class:`ghillie.estate.ports.EstateManagement` and back. They never import
catalogue, registry, or SQLAlchemy modules: every failure they can see is an
:mod:`ghillie.estate.errors` type, mapped centrally by
:mod:`ghillie.api.errors`.
"""

import typing as typ
from http import HTTPStatus

import falcon
import msgspec

from ghillie.api.errors import InvalidInputError, PayloadTooLargeError
from ghillie.api.estate.schemas import (
    CatalogueImportResponse,
    CountResponse,
    EstateListResponse,
    EstateSummaryResponse,
    ImportCatalogueRequest,
    IngestionRequest,
    IngestionToggleResponse,
    LastImportResponse,
    RegistrySyncResponse,
    RepositoryListResponse,
    RepositoryResponse,
)
from ghillie.estate.models import (
    DEFAULT_PAGE_LIMIT,
    MAX_REQUEST_BODY_BYTES,
    CatalogueImportSummary,
    CountSummary,
    EstateSummary,
    IngestionToggleOutcome,
    Page,
    PageRequest,
    RegistrySyncSummary,
    RepositoryPage,
    RepositoryQuery,
)

if typ.TYPE_CHECKING:
    from falcon.asgi import Request, Response

    from ghillie.estate.ports import EstateManagement

__all__ = [
    "CatalogueImportResource",
    "EstateCollectionResource",
    "EstateRepositoryCollectionResource",
    "RegistrySyncResource",
    "RepositoryIngestionResource",
]

_JSON_ONLY = frozenset({"application/json"})
_PATCH_MEDIA_TYPES = frozenset({"application/json", "application/merge-patch+json"})


def _content_type(req: Request) -> str:
    """Return the bare, lower-cased media type of the request."""
    raw = req.get_header("Content-Type") or ""
    return raw.split(";", 1)[0].strip().lower()


def _require_media_type(req: Request, allowed: frozenset[str]) -> None:
    """Raise a 415 unless the request media type is in *allowed*."""
    if _content_type(req) in allowed:
        return
    raise falcon.HTTPUnsupportedMediaType(
        title="Unsupported media type",
        description=f"expected {' or '.join(sorted(allowed))}",
    )


def _single_param(req: Request, name: str) -> str | None:
    """Return one query parameter, rejecting repeated occurrences."""
    values = req.get_param_as_list(name)
    if values is None:
        return None
    if len(values) != 1:
        message = "must be supplied at most once"
        raise InvalidInputError(message, field=name)
    value = values[0]
    if not isinstance(value, str):
        message = "must be supplied as text"
        raise InvalidInputError(message, field=name)
    return value


def _int_param(req: Request, name: str, default: int) -> int:
    """Parse an integer query parameter or raise ``invalid_input``."""
    raw = _single_param(req, name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        message = "must be an integer"
        raise InvalidInputError(message, field=name) from exc


def _optional_bool_param(req: Request, name: str) -> bool | None:
    """Parse a strict ``true``/``false`` query parameter."""
    raw = _single_param(req, name)
    if raw is None:
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    message = 'must be "true" or "false"'
    raise InvalidInputError(message, field=name)


def _flag_param(req: Request, name: str) -> bool:
    """Parse a boolean flag that defaults to ``False``."""
    value = _optional_bool_param(req, name)
    return value if value is not None else False


async def _read_body(req: Request) -> bytes:
    """Read the request body, refusing anything over the documented limit.

    The declared ``Content-Length`` is checked first so an oversized upload is
    rejected without buffering it. Reading one byte past the limit covers
    chunked requests that declare no length.
    """
    declared = req.content_length
    if declared is not None and declared > MAX_REQUEST_BODY_BYTES:
        raise PayloadTooLargeError(MAX_REQUEST_BODY_BYTES)
    body = await req.stream.read(MAX_REQUEST_BODY_BYTES + 1)
    if len(body) > MAX_REQUEST_BODY_BYTES:
        raise PayloadTooLargeError(MAX_REQUEST_BODY_BYTES)
    return body


def _decode_body[BodyT: msgspec.Struct](body: bytes, struct_type: type[BodyT]) -> BodyT:
    """Decode a JSON body into *struct_type* or raise ``invalid_input``."""
    try:
        return msgspec.json.decode(body, type=struct_type)
    except msgspec.DecodeError as exc:
        message = f"invalid request body: {exc}"
        raise InvalidInputError(message) from exc


def _page_request(req: Request) -> PageRequest:
    """Build a validated pagination request from the query string."""
    return PageRequest(
        limit=_int_param(req, "limit", DEFAULT_PAGE_LIMIT),
        offset=_int_param(req, "offset", 0),
    )


def _estate_list_response(page: Page[EstateSummary]) -> EstateListResponse:
    """Convert an estate page into its wire representation."""
    return EstateListResponse(
        items=[_estate_summary(item) for item in page.items],
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
        next_offset=page.next_offset,
    )


def _estate_summary(item: EstateSummary) -> EstateSummaryResponse:
    """Convert one estate summary into its wire representation."""
    last_import = None
    if item.last_import_commit_sha is not None and item.last_imported_at is not None:
        last_import = LastImportResponse(
            commit_sha=item.last_import_commit_sha,
            imported_at=item.last_imported_at,
        )
    return EstateSummaryResponse(
        key=item.key,
        name=item.name,
        description=item.description,
        last_import=last_import,
    )


def _counts(summary: CountSummary) -> CountResponse:
    """Convert a count summary into its wire representation."""
    return CountResponse(
        created=summary.created,
        updated=summary.updated,
        deleted=summary.deleted,
    )


def _import_response(summary: CatalogueImportSummary) -> CatalogueImportResponse:
    """Convert an import summary into its wire representation."""
    return CatalogueImportResponse(
        estate_key=summary.estate_key,
        commit_sha=summary.commit_sha,
        state=summary.state,
        dry_run=summary.dry_run,
        skipped=summary.skipped,
        skipped_reason=summary.skipped_reason,
        registry_sync_required=summary.registry_sync_required,
        projects=_counts(summary.projects),
        components=_counts(summary.components),
        repositories=_counts(summary.repositories),
        edges=_counts(summary.edges),
    )


def _sync_response(summary: RegistrySyncSummary) -> RegistrySyncResponse:
    """Convert a registry sync summary into its wire representation."""
    return RegistrySyncResponse(
        estate_key=summary.estate_key,
        state=summary.state,
        dry_run=summary.dry_run,
        repositories_created=summary.repositories_created,
        repositories_updated=summary.repositories_updated,
        repositories_deactivated=summary.repositories_deactivated,
        repositories_conflicted=list(summary.repositories_conflicted),
        repositories_left_disabled=list(summary.repositories_left_disabled),
        repositories_left_disabled_count=summary.repositories_left_disabled_count,
    )


def _repository_page_response(page: RepositoryPage) -> RepositoryListResponse:
    """Convert a repository page into its wire representation."""
    return RepositoryListResponse(
        estate_key=page.estate_key,
        items=[
            RepositoryResponse(
                owner=repository.owner,
                name=repository.name,
                default_branch=repository.default_branch,
                ingestion_enabled=repository.ingestion_enabled,
                documentation_paths=list(repository.documentation_paths),
            )
            for repository in page.items
        ],
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
        next_offset=page.next_offset,
    )


def _toggle_response(
    outcome: IngestionToggleOutcome,
) -> IngestionToggleResponse:
    """Convert a toggle outcome into its wire representation."""
    return IngestionToggleResponse(
        owner=outcome.owner,
        name=outcome.name,
        ingestion_enabled=outcome.ingestion_enabled,
        changed=outcome.changed,
    )


class EstateCollectionResource:
    """Resource for ``GET /estates``."""

    def __init__(self, *, estates: EstateManagement) -> None:
        """Store the estate-management port."""
        self._estates = estates

    async def on_get(self, req: Request, resp: Response) -> None:
        """Return a page of estates.

        Parameters
        ----------
        req
            Request whose ``limit`` and ``offset`` query parameters select the
            page.
        resp
            Response that receives the estate page.

        Raises
        ------
        InvalidInputError
            If a pagination parameter is malformed or supplied twice.
        InvalidPaginationError
            If the requested limit or offset is outside the documented bounds.
        StorageUnavailableError
            If the catalogue store cannot be read.

        """
        page = await self._estates.list_estates(_page_request(req))
        resp.media = msgspec.to_builtins(_estate_list_response(page))
        resp.status = HTTPStatus.OK


class CatalogueImportResource:
    """Resource for ``POST /estates/{estate_key}/catalogue-import``."""

    def __init__(self, *, estates: EstateManagement) -> None:
        """Store the estate-management port."""
        self._estates = estates

    async def on_post(
        self,
        req: Request,
        resp: Response,
        *,
        estate_key: str,
    ) -> None:
        """Import one catalogue document for an estate.

        Parameters
        ----------
        req
            JSON request whose body carries the catalogue document, commit
            SHA, and optional estate name; ``dry_run`` is a query parameter.
        resp
            Response that receives the import summary.
        estate_key
            Key of the estate to create or update.

        Raises
        ------
        falcon.HTTPUnsupportedMediaType
            If the request is not ``application/json``.
        InvalidInputError
            If the body is malformed or ``dry_run`` is not ``true``/``false``.
        PayloadTooLargeError
            If the body exceeds the documented limit.
        InvalidEstateKeyError
            If a new estate's key does not match the creation pattern.
        CatalogueRejectedError
            If the document fails catalogue validation.
        EstateConflictError
            If a concurrent import claims the same uniqueness constraint.
        StorageUnavailableError
            If the catalogue store cannot be written.

        """
        _require_media_type(req, _JSON_ONLY)
        body = _decode_body(await _read_body(req), ImportCatalogueRequest)
        summary = await self._estates.import_catalogue(
            estate_key,
            catalogue_yaml=body.catalogue_yaml,
            commit_sha=body.commit_sha,
            estate_name=body.estate_name,
            dry_run=_flag_param(req, "dry_run"),
        )
        resp.media = msgspec.to_builtins(_import_response(summary))
        resp.status = HTTPStatus.OK


class RegistrySyncResource:
    """Resource for ``POST /estates/{estate_key}/registry-sync``."""

    def __init__(self, *, estates: EstateManagement) -> None:
        """Store the estate-management port."""
        self._estates = estates

    async def on_post(
        self,
        req: Request,
        resp: Response,
        *,
        estate_key: str,
    ) -> None:
        """Project an estate's catalogue into the registry.

        Parameters
        ----------
        req
            Request whose ``dry_run`` query parameter selects the mode.
        resp
            Response that receives the sync summary.
        estate_key
            Key of the estate whose catalogue is projected.

        Raises
        ------
        InvalidInputError
            If ``dry_run`` is not ``true`` or ``false``.
        EstateNotFoundError
            If no estate has the supplied key.
        EstateConflictError
            If a concurrent sync claims the same uniqueness constraint.
        StorageUnavailableError
            If the registry store cannot be written.
        RegistrySyncFailedError
            If the registry reports any other failure.

        """
        summary = await self._estates.sync_registry(
            estate_key, dry_run=_flag_param(req, "dry_run")
        )
        resp.media = msgspec.to_builtins(_sync_response(summary))
        resp.status = HTTPStatus.OK


class EstateRepositoryCollectionResource:
    """Resource for ``GET /estates/{estate_key}/repositories``."""

    def __init__(self, *, estates: EstateManagement) -> None:
        """Store the estate-management port."""
        self._estates = estates

    async def on_get(
        self,
        req: Request,
        resp: Response,
        *,
        estate_key: str,
    ) -> None:
        """Return a page of an estate's registered repositories.

        Parameters
        ----------
        req
            Request whose ``ingestion_enabled``, ``limit``, and ``offset``
            query parameters select and filter the page.
        resp
            Response that receives the repository page.
        estate_key
            Key of the estate whose repositories are listed.

        Raises
        ------
        InvalidInputError
            If a query parameter is malformed or supplied twice.
        InvalidPaginationError
            If the requested limit or offset is outside the documented bounds.
        EstateNotFoundError
            If no estate has the supplied key.
        StorageUnavailableError
            If the registry store cannot be read.

        """
        query = RepositoryQuery(
            ingestion_enabled=_optional_bool_param(req, "ingestion_enabled"),
            limit=_int_param(req, "limit", DEFAULT_PAGE_LIMIT),
            offset=_int_param(req, "offset", 0),
        )
        page = await self._estates.list_repositories(estate_key, query)
        resp.media = msgspec.to_builtins(_repository_page_response(page))
        resp.status = HTTPStatus.OK


class RepositoryIngestionResource:
    """Resource for ``PATCH /repositories/{owner}/{name}/ingestion``."""

    def __init__(self, *, estates: EstateManagement) -> None:
        """Store the estate-management port."""
        self._estates = estates

    async def on_patch(
        self,
        req: Request,
        resp: Response,
        *,
        owner: str,
        name: str,
    ) -> None:
        """Set one repository's ingestion flag.

        Parameters
        ----------
        req
            JSON or merge-patch request whose body carries the new flag.
        resp
            Response that receives the toggle outcome.
        owner
            GitHub owner of the repository.
        name
            GitHub name of the repository.

        Raises
        ------
        falcon.HTTPUnsupportedMediaType
            If the request media type is not accepted.
        InvalidInputError
            If the body is malformed.
        PayloadTooLargeError
            If the body exceeds the documented limit.
        RepositoryNotFoundError
            If no registered repository has that owner and name.
        StorageUnavailableError
            If the registry store cannot be written.

        """
        _require_media_type(req, _PATCH_MEDIA_TYPES)
        body = _decode_body(await _read_body(req), IngestionRequest)
        outcome = await self._estates.set_ingestion(
            owner, name, enabled=body.ingestion_enabled
        )
        resp.media = msgspec.to_builtins(_toggle_response(outcome))
        resp.status = HTTPStatus.OK
