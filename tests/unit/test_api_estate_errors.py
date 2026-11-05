"""Domain-error to HTTP-response translation for estate endpoints.

These tests are the server half of obligation O4: every documented failure
mode returns the documented status and stable ``code``.
"""

from __future__ import annotations

import asyncio
import typing as typ

import falcon.testing
import httpx
import pytest

from ghillie.api.app import AppDependencies, create_app
from ghillie.catalogue.importer import CatalogueImporter
from ghillie.estate.errors import (
    CatalogueRejectedError,
    EstateConflictError,
    EstateNotFoundError,
    InvalidEstateKeyError,
    InvalidPaginationError,
    Issue,
    RegistrySyncFailedError,
    RepositoryNotFoundError,
    StorageUnavailableError,
)
from tests.helpers.femtologging_capture import capture_femto_logs
from tests.unit.estate_test_helpers import (
    build_registry,
    build_service,
    catalogue_document,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.estate.models import (
        CatalogueImportRequest,
        CatalogueImportSummary,
        EstateSummary,
        IngestionToggleOutcome,
        Page,
        PageRequest,
        RegistrySyncSummary,
        RepositoryPage,
        RepositoryQuery,
    )


class _RaisingEstateManagement:
    """Port double whose every operation raises the configured exception."""

    def __init__(self, error: Exception) -> None:
        """Store the exception every method raises."""
        self._error = error

    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]:
        """Raise the configured error."""
        raise self._error

    async def import_catalogue(
        self, estate_key: str, request: CatalogueImportRequest
    ) -> CatalogueImportSummary:
        """Raise the configured error."""
        raise self._error

    async def sync_registry(
        self, estate_key: str, *, dry_run: bool
    ) -> RegistrySyncSummary:
        """Raise the configured error."""
        raise self._error

    async def list_repositories(
        self, estate_key: str, query: RepositoryQuery
    ) -> RepositoryPage:
        """Raise the configured error."""
        raise self._error

    async def set_ingestion(
        self, owner: str, name: str, *, enabled: bool
    ) -> IngestionToggleOutcome:
        """Raise the configured error."""
        raise self._error


def _client(error: Exception) -> falcon.testing.TestClient:
    """Build a client whose estate port raises *error*."""
    service = _RaisingEstateManagement(error)
    return falcon.testing.TestClient(
        create_app(AppDependencies(estate_service=service))
    )


_IMPORT_BODY = {"commit_sha": "c1", "catalogue_yaml": "version: 1\n"}


class _ErrorBody(typ.TypedDict, total=False):
    """Documented error-envelope fields these assertions inspect."""

    title: str
    description: str
    code: str
    field: str
    issues: list[dict[str, str]]
    max_bytes: int


def _assert_error(
    result: falcon.testing.Result,
    *,
    status: int,
    code: str,
) -> _ErrorBody:
    """Assert a structured error body and return it."""
    assert result.status_code == status, result.text
    body = typ.cast("_ErrorBody", result.json)
    assert body["code"] == code, "error body should carry the expected code"
    assert isinstance(body["title"], str), "title should be a string"
    assert body["title"], "title should be present"
    assert isinstance(body["description"], str), "description should be a string"
    return body


def test_unexpected_error_uses_the_envelope() -> None:
    """An unhandled exception still yields the shared 500 body (D7)."""
    result = _client(RuntimeError("boom")).simulate_get("/estates")

    body = _assert_error(result, status=500, code="internal_error")
    assert "boom" not in result.text, "internal errors must not leak details"
    assert body["description"] == "An unexpected error occurred.", (
        "description should use the generic message"
    )


def test_invalid_estate_key_is_invalid_input() -> None:
    """A key that fails the creation pattern is a 400."""
    error = InvalidEstateKeyError("bad key", "must match the pattern")
    result = _client(error).simulate_post(
        "/estates/bad key/catalogue-import", json=_IMPORT_BODY
    )

    body = _assert_error(result, status=400, code="invalid_input")
    assert body["field"] == "estate_key", "error should name the estate key"


def test_invalid_pagination_is_invalid_input() -> None:
    """A bad page limit is a 400 that names the field."""
    error = InvalidPaginationError("limit", "must be between 1 and 500")
    result = _client(error).simulate_get("/estates", params={"limit": "0"})

    body = _assert_error(result, status=400, code="invalid_input")
    assert body["field"] == "limit", "error should name the limit field"
    assert body["description"] == "must be between 1 and 500", (
        "description should explain the limit"
    )


def test_catalogue_rejected_is_unprocessable() -> None:
    """Catalogue validation issues are a 422 with a list of issues."""
    error = CatalogueRejectedError(
        (
            Issue(code="catalogue_schema", message="projects: required"),
            Issue(code="catalogue_schema", message="components: invalid"),
        )
    )
    result = _client(error).simulate_post(
        "/estates/demo/catalogue-import", json=_IMPORT_BODY
    )

    body = _assert_error(result, status=422, code="catalogue_invalid")
    assert body["issues"] == [
        {"code": "catalogue_schema", "message": "projects: required"},
        {"code": "catalogue_schema", "message": "components: invalid"},
    ], "issues should list both failures"


def test_estate_not_found() -> None:
    """An unknown estate is a 404 with its own stable code."""
    error = EstateNotFoundError("missing")
    result = _client(error).simulate_post("/estates/missing/registry-sync")

    body = _assert_error(result, status=404, code="estate_not_found")
    assert "missing" in body["description"], "description should name the estate"


def test_repository_not_found() -> None:
    """An unknown repository is a 404 with its own stable code."""
    error = RepositoryNotFoundError("org", "alpha")
    result = _client(error).simulate_patch(
        "/repositories/org/alpha/ingestion",
        body=b'{"ingestion_enabled": true}',
        headers={"Content-Type": "application/json"},
    )

    body = _assert_error(result, status=404, code="repository_not_found")
    assert "org/alpha" in body["description"], "description should name the repository"


def test_conflict() -> None:
    """A uniqueness conflict is a 409."""
    error = EstateConflictError("the write conflicts with an existing record")
    result = _client(error).simulate_post(
        "/estates/demo/catalogue-import", json=_IMPORT_BODY
    )

    _assert_error(result, status=409, code="conflict")


def test_storage_unavailable() -> None:
    """An unreachable database is a 503."""
    error = StorageUnavailableError("storage is unavailable")
    result = _client(error).simulate_get("/estates")

    _assert_error(result, status=503, code="storage_unavailable")


def test_registry_sync_failed() -> None:
    """Any other sync failure is a 500 with its own stable code."""
    error = RegistrySyncFailedError("the registry sync failed")
    result = _client(error).simulate_post("/estates/demo/registry-sync")

    _assert_error(result, status=500, code="registry_sync_failed")


def test_storage_unavailable_is_logged() -> None:
    """A handled 503 still leaves an operator-visible record."""
    error = StorageUnavailableError("storage is unavailable")

    with capture_femto_logs("ghillie.api.errors") as logs:
        _client(error).simulate_get("/estates")
        logs.wait_for_timeout()

    assert any("Storage unavailable" in record.message for record in logs.records), (
        "handled 503 responses should be logged"
    )


def test_registry_sync_failed_is_logged() -> None:
    """A handled server-side failure still leaves an operator-visible log."""
    error = RegistrySyncFailedError("the registry sync failed")

    with capture_femto_logs("ghillie.api.errors") as logs:
        _client(error).simulate_post("/estates/demo/registry-sync")
        logs.wait_for_timeout()

    assert any("Registry sync failed" in record.message for record in logs.records), (
        "handled 500 responses should be logged"
    )


def test_unroutable_path_is_not_found() -> None:
    """An unknown path is a structured 404."""
    result = _client(StorageUnavailableError("unused")).simulate_get("/nope")

    _assert_error(result, status=404, code="not_found")


def test_wrong_method_is_method_not_allowed() -> None:
    """A known path with an unsupported method is a structured 405."""
    result = _client(StorageUnavailableError("unused")).simulate_delete("/estates")

    _assert_error(result, status=405, code="method_not_allowed")


def _no_storage_details(text: str) -> bool:
    """Return true when *text* carries no SQL or driver detail (D7)."""
    lowered = text.lower()
    forbidden = ("insert into", "duplicate key", "unique constraint", "asyncpg")
    return not any(fragment in lowered for fragment in forbidden)


@pytest.mark.asyncio
async def test_over_long_field_is_invalid_input_through_the_real_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """O4: the over-long-field row holds over the real service and database."""
    service = build_service(session_factory, build_registry(session_factory))
    app = create_app(AppDependencies(estate_service=service))
    transport = httpx.ASGITransport(app=typ.cast("typ.Any", app))
    body = {
        "commit_sha": "c1",
        "catalogue_yaml": "version: 1\n",
        "estate_name": "x" * 256,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/estates/demo/catalogue-import", json=body)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "invalid_input", "expected invalid_input"
    assert _no_storage_details(response.text), "the body must not leak storage detail"


@pytest.mark.asyncio
async def test_conflict_through_the_real_service_is_a_409(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O4: a real uniqueness conflict becomes a 409 without database detail.

    Two app instances share one database, and neither can see the other's
    uncommitted estate. A barrier releases both imports after their existence
    check, so the loser's flush hits the unique key and the service translates
    the resulting ``IntegrityError``.
    """
    registry = build_registry(session_factory)
    apps = [
        create_app(
            AppDependencies(estate_service=build_service(session_factory, registry))
        )
        for _ in range(2)
    ]
    barrier = asyncio.Barrier(2)
    original = CatalogueImporter._ensure_estate

    async def _synchronized(self: CatalogueImporter, session: AsyncSession) -> object:
        await barrier.wait()
        return await original(self, session)

    monkeypatch.setattr(CatalogueImporter, "_ensure_estate", _synchronized)
    body = {"commit_sha": "c1", "catalogue_yaml": catalogue_document()}

    async def _import(app: object) -> httpx.Response:
        transport = httpx.ASGITransport(app=typ.cast("typ.Any", app))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post("/estates/demo/catalogue-import", json=body)

    responses = await asyncio.wait_for(
        asyncio.gather(*(_import(app) for app in apps)), timeout=30
    )

    assert sorted(response.status_code for response in responses) == [200, 409], (
        "one import should succeed and the other should conflict"
    )
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["code"] == "conflict", "expected the conflict code"
    assert _no_storage_details(conflict.text), "the body must not leak storage detail"


def test_falcon_http_error_keeps_its_description() -> None:
    """Falcon's own HTTP errors are rendered through the same envelope."""
    result = _client(StorageUnavailableError("unused")).simulate_post(
        "/estates/demo/catalogue-import",
        body="{}",
        headers={"Content-Type": "text/plain"},
    )

    _assert_error(result, status=415, code="unsupported_media_type")
    assert "application/json" in result.json["description"], (
        "the Falcon error's own description should reach the envelope"
    )
