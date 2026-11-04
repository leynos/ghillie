"""HTTP resource behaviour for estate listing, import, and synchronization.

The resources are exercised against a fake :class:`EstateManagement` port so
these tests describe only the transport contract: paths, query parsing, strict
booleans, request bodies, and response shapes. Translation of domain failures
is covered by ``test_api_estate_errors.py``; repository listing and ingestion
toggles are covered by ``test_api_repository_resources.py``.
"""

import json
import typing as typ

import httpx
import pytest

from ghillie.api.app import AppDependencies, create_app
from ghillie.estate.models import EstateSummary, PageRequest
from tests.unit.estate_test_helpers import FakeEstateManagement, build_estate_client

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    import falcon.testing

_MAX_REQUEST_BODY_BYTES = 1024 * 1024


@pytest.fixture
def service() -> FakeEstateManagement:
    """Return a fresh fake port."""
    return FakeEstateManagement()


@pytest.fixture
def client(service: FakeEstateManagement) -> falcon.testing.TestClient:
    """Build a client over the fake port."""
    return build_estate_client(service)


# ---------------------------------------------------------------------------
# GET /estates
# ---------------------------------------------------------------------------


def test_list_estates_returns_the_documented_envelope(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """The default listing returns every documented field."""
    result = client.simulate_get("/estates")

    assert result.status_code == 200, "expected 200 from /estates"
    assert service.page_requests == [PageRequest()], "default page request expected"
    assert result.json == {
        "items": [
            {
                "key": "demo",
                "name": "Demo",
                "description": "A demo estate",
                "last_import": {
                    "commit_sha": "c1",
                    "imported_at": "2024-07-07T12:00:00Z",
                },
            }
        ],
        "limit": 50,
        "offset": 0,
        "has_more": False,
        "next_offset": None,
    }, "documented envelope expected"


def test_list_estates_parses_pagination(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """Limit and offset reach the port as integers."""
    result = client.simulate_get("/estates", params={"limit": "2", "offset": "3"})

    assert result.status_code == 200, "expected 200 from /estates"
    assert service.page_requests == [PageRequest(limit=2, offset=3)], (
        "limit and offset should reach the service"
    )
    assert result.json["limit"] == 2, "limit should echo the request"
    assert result.json["offset"] == 3, "offset should echo the request"


def test_list_estates_renders_a_null_last_import(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """An estate that has never been imported has a null ``last_import``."""
    service.estate_items = (
        EstateSummary(
            key="fresh",
            name="Fresh",
            description=None,
            last_import_commit_sha=None,
            last_imported_at=None,
        ),
    )

    result = client.simulate_get("/estates")

    assert result.status_code == 200, "expected 200 from /estates"
    assert result.json["items"][0]["last_import"] is None, "last import should be null"
    assert result.json["items"][0]["description"] is None, "description should be null"


def test_list_estates_offset_past_end_is_empty(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """An offset past the last estate returns an empty last page."""
    service.estate_items = ()

    result = client.simulate_get("/estates", params={"offset": "25"})

    assert result.status_code == 200, "expected 200 from /estates"
    assert result.json["items"] == [], "empty page should have no items"
    assert result.json["has_more"] is False, "empty page should not have more"
    assert result.json["next_offset"] is None, "no next offset on last page"


@pytest.mark.parametrize("value", ["abc", "1.5", ""])
def test_list_estates_rejects_a_non_integer_limit(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
    value: str,
) -> None:
    """A limit that is not an integer is invalid input."""
    result = client.simulate_get("/estates", params={"limit": value})

    assert result.status_code == 400, "expected 400 for a bad limit"
    assert result.json["code"] == "invalid_input", "code should be invalid_input"
    assert result.json["field"] == "limit", "error should name the limit field"
    assert service.page_requests == [], "invalid input should not reach the service"


def test_list_estates_rejects_a_repeated_query_parameter(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """A repeated pagination parameter is ambiguous and rejected."""
    result = client.simulate_get("/estates?limit=1&limit=2")

    assert result.status_code == 400, "expected 400 for a repeated limit"
    assert result.json["code"] == "invalid_input", "code should be invalid_input"
    assert result.json["field"] == "limit", "error should name the limit field"
    assert service.page_requests == [], "invalid input should not reach the service"


# ---------------------------------------------------------------------------
# POST /estates/{estate_key}/catalogue-import
# ---------------------------------------------------------------------------


_IMPORT_BODY = {
    "commit_sha": "c1",
    "estate_name": "Demo",
    "catalogue_yaml": "version: 1\n",
}


def test_import_returns_the_documented_envelope(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """A successful import echoes counts and the skip state."""
    result = client.simulate_post(
        "/estates/demo/catalogue-import",
        json=_IMPORT_BODY,
    )

    assert result.status_code == 200, "expected 200 from catalogue-import"
    assert service.imports == [
        {
            "estate_key": "demo",
            "catalogue_yaml": "version: 1\n",
            "commit_sha": "c1",
            "estate_name": "Demo",
            "dry_run": False,
        }
    ], "import arguments should reach the service"
    assert result.json == {
        "estate_key": "demo",
        "commit_sha": "c1",
        "state": "succeeded",
        "dry_run": False,
        "skipped": False,
        "skipped_reason": None,
        "registry_sync_required": True,
        "projects": {"created": 1, "updated": 0, "deleted": 0},
        "components": {"created": 2, "updated": 0, "deleted": 1},
        "repositories": {"created": 1, "updated": 0, "deleted": 0},
        "edges": {"created": 1, "updated": 0, "deleted": 0},
    }, "documented import envelope expected"


def test_import_accepts_a_null_estate_name(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """``estate_name`` is optional and may be null."""
    result = client.simulate_post(
        "/estates/demo/catalogue-import",
        json={"commit_sha": "c1", "estate_name": None, "catalogue_yaml": "x"},
    )

    assert result.status_code == 200, "expected 200 from catalogue-import"
    assert service.imports[0]["estate_name"] is None, "estate name should be null"


def test_import_parses_dry_run(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """``?dry_run=true`` reaches the port and clears registry sync."""
    result = client.simulate_post(
        "/estates/demo/catalogue-import",
        params={"dry_run": "true"},
        json=_IMPORT_BODY,
    )

    assert result.status_code == 200, "expected 200 from catalogue-import"
    assert service.imports[0]["dry_run"] is True, "dry run should reach the service"
    assert result.json["dry_run"] is True, "response should be a dry run"
    assert result.json["registry_sync_required"] is False, "no registry sync on dry run"


def test_import_rejects_a_non_boolean_dry_run(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """Only ``true`` and ``false`` are boolean query values."""
    result = client.simulate_post(
        "/estates/demo/catalogue-import",
        params={"dry_run": "yes"},
        json=_IMPORT_BODY,
    )

    assert result.status_code == 400, "expected 400 for a bad boolean"
    assert result.json["code"] == "invalid_input", "code should be invalid_input"
    assert result.json["field"] == "dry_run", "error should name dry_run"
    assert service.imports == [], "invalid input should not reach the service"


def test_import_rejects_an_unsupported_media_type(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """A non-JSON body is rejected before it is read."""
    result = client.simulate_post(
        "/estates/demo/catalogue-import",
        body=b"version: 1",
        headers={"Content-Type": "text/yaml"},
    )

    assert result.status_code == 415, "expected 415 for a YAML body"
    assert result.json["code"] == "unsupported_media_type", "unsupported media type"
    assert service.imports == [], "invalid input should not reach the service"


def test_import_rejects_a_body_over_the_limit_by_content_length(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """The declared Content-Length trips the size check before reading."""
    result = client.simulate_post(
        "/estates/demo/catalogue-import",
        body=b"x" * (_MAX_REQUEST_BODY_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )

    assert result.status_code == 413, "expected 413 for an oversized body"
    assert result.json["code"] == "payload_too_large", "expected payload_too_large code"
    assert result.json["max_bytes"] == _MAX_REQUEST_BODY_BYTES, "max bytes should match"
    assert service.imports == [], "invalid input should not reach the service"


@pytest.mark.asyncio
async def test_import_rejects_a_streamed_body_over_the_limit() -> None:
    """A chunked body is stopped after one byte over the limit."""
    service = FakeEstateManagement()
    app = create_app(AppDependencies(estate_service=service))
    # Falcon annotates the ASGI scope more narrowly than httpx's transport
    # protocol expects, though the runtime contract is identical.
    transport = httpx.ASGITransport(app=typ.cast("typ.Any", app))

    async def oversize() -> cabc.AsyncIterator[bytes]:
        yield b"x" * (_MAX_REQUEST_BODY_BYTES + 1)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/estates/demo/catalogue-import",
            content=oversize(),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413, "expected 413 for a streamed body"
    assert response.json()["code"] == "payload_too_large", "expected payload_too_large"
    assert response.json()["max_bytes"] == _MAX_REQUEST_BODY_BYTES, (
        "max bytes should match"
    )
    assert service.imports == [], "invalid input should not reach the service"


@pytest.mark.asyncio
async def test_import_accepts_a_body_split_across_chunks() -> None:
    """A chunked upload is assembled completely before it is decoded.

    Falcon's stream returns as much as the requested size allows, even when
    the transport delivers the body in many small ASGI events. This pins that
    behaviour so a future reader cannot silently decode only the first chunk.
    """
    service = FakeEstateManagement()
    app = create_app(AppDependencies(estate_service=service))
    transport = httpx.ASGITransport(app=typ.cast("typ.Any", app))
    body = json.dumps(_IMPORT_BODY).encode()

    async def chunks() -> cabc.AsyncIterator[bytes]:
        for start in range(0, len(body), 8):
            yield body[start : start + 8]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/estates/demo/catalogue-import",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 200, response.text
    assert service.imports == [
        {
            "estate_key": "demo",
            "catalogue_yaml": "version: 1\n",
            "commit_sha": "c1",
            "estate_name": "Demo",
            "dry_run": False,
        }
    ], "the whole chunked body should reach the service"


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"{", "application/json"),
        (b"", "application/json"),
        (b'{"commit_sha": "c1"}', "application/json"),
        (b'{"commit_sha": null, "catalogue_yaml": "x"}', "application/json"),
        (b'{"commit_sha": "", "catalogue_yaml": "x"}', "application/json"),
        (
            b'{"commit_sha": "c1", "catalogue_yaml": "x", "extra": 1}',
            "application/json",
        ),
        (
            b'{"commit_sha": "c1", "catalogue_yaml": "x", "estate_name": ""}',
            "application/json",
        ),
    ],
)
def test_import_rejects_a_malformed_or_incomplete_body(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
    body: bytes,
    content_type: str,
) -> None:
    """Malformed, missing, null, unknown, and over-long fields are 400."""
    result = client.simulate_post(
        "/estates/demo/catalogue-import",
        body=body,
        headers={"Content-Type": content_type},
    )

    assert result.status_code == 400, "expected 400 for a malformed body"
    assert result.json["code"] == "invalid_input", "code should be invalid_input"
    assert service.imports == [], "invalid input should not reach the service"


# ---------------------------------------------------------------------------
# POST /estates/{estate_key}/registry-sync
# ---------------------------------------------------------------------------


def test_sync_returns_the_documented_envelope(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """A sync echoes counts, conflicted slugs, and the disabled preview."""
    result = client.simulate_post("/estates/demo/registry-sync")

    assert result.status_code == 200, "expected 200 from registry-sync"
    assert service.syncs == [{"estate_key": "demo", "dry_run": False}], (
        "sync call should reach the service"
    )
    assert result.json == {
        "estate_key": "demo",
        "state": "succeeded",
        "dry_run": False,
        "repositories_created": 1,
        "repositories_updated": 2,
        "repositories_deactivated": 0,
        "repositories_conflicted": ["other/estate-repo"],
        "repositories_left_disabled": ["org/alpha"],
        "repositories_left_disabled_count": 1,
    }, "documented sync envelope expected"


def test_sync_parses_dry_run(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """A dry-run sync is forwarded to the port."""
    result = client.simulate_post(
        "/estates/demo/registry-sync", params={"dry_run": "true"}
    )

    assert result.status_code == 200, "expected 200 from registry-sync"
    assert service.syncs == [{"estate_key": "demo", "dry_run": True}], (
        "dry-run sync should reach the service"
    )
    assert result.json["dry_run"] is True, "response should be a dry run"


@pytest.mark.parametrize("value", ["1", "TRUE", "on", ""])
def test_sync_rejects_a_non_boolean_dry_run(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
    value: str,
) -> None:
    """Boolean query values are strict and lower-case."""
    result = client.simulate_post(
        "/estates/demo/registry-sync", params={"dry_run": value}
    )

    assert result.status_code == 400, "expected 400 for a bad boolean"
    assert result.json["code"] == "invalid_input", "code should be invalid_input"
    assert service.syncs == [], "invalid input should not reach the service"


# ---------------------------------------------------------------------------
# Unknown query parameter combinations
# ---------------------------------------------------------------------------


def test_unknown_extra_query_parameter_is_ignored(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """Unknown query parameters do not change the documented behaviour."""
    result = client.simulate_get("/estates", params={"unknown": "value"})

    assert result.status_code == 200, "expected 200 from /estates"
    assert service.page_requests == [PageRequest()], "default page request expected"
