"""HTTP resource behaviour for the estate-management endpoints.

The resources are exercised against a fake :class:`EstateManagement` port so
these tests describe only the transport contract: paths, query parsing, strict
booleans, request bodies, and response shapes. Translation of domain failures
is covered by ``test_api_estate_errors.py``.
"""

import datetime as dt
import typing as typ

import falcon.testing
import httpx
import pytest

from ghillie.api.app import AppDependencies, create_app
from ghillie.estate.models import (
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
from ghillie.registry.models import RepositoryInfo

_NOW = dt.datetime(2024, 7, 7, 12, 0, tzinfo=dt.UTC)
_MAX_REQUEST_BODY_BYTES = 1024 * 1024
_DOCUMENTATION_PATHS = ("docs/", "README.md")


class FakeEstateManagement:
    """In-memory port double that records every call."""

    def __init__(self) -> None:
        """Build a double with one estate and one repository."""
        self.page_requests: list[PageRequest] = []
        self.repository_queries: list[RepositoryQuery] = []
        self.imports: list[dict[str, object]] = []
        self.syncs: list[dict[str, object]] = []
        self.toggles: list[dict[str, object]] = []
        self.estate_items: tuple[EstateSummary, ...] = (
            EstateSummary(
                key="demo",
                name="Demo",
                description="A demo estate",
                last_import_commit_sha="c1",
                last_imported_at=_NOW,
            ),
        )
        self.repository_items: tuple[RepositoryInfo, ...] = (
            RepositoryInfo(
                id="repo-1",
                owner="org",
                name="alpha",
                default_branch="main",
                ingestion_enabled=True,
                documentation_paths=_DOCUMENTATION_PATHS,
                estate_id="estate-1",
            ),
        )

    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]:
        """Return the configured estate page."""
        self.page_requests.append(page)
        return Page(
            items=self.estate_items,
            limit=page.limit,
            offset=page.offset,
            has_more=False,
            next_offset=None,
        )

    async def import_catalogue(  # noqa: PLR0913 - mirrors the port signature.
        self,
        estate_key: str,
        *,
        catalogue_yaml: str,
        commit_sha: str,
        estate_name: str | None,
        dry_run: bool,
    ) -> CatalogueImportSummary:
        """Record and return a fixed import summary."""
        self.imports.append(
            {
                "estate_key": estate_key,
                "catalogue_yaml": catalogue_yaml,
                "commit_sha": commit_sha,
                "estate_name": estate_name,
                "dry_run": dry_run,
            }
        )
        return CatalogueImportSummary(
            estate_key=estate_key,
            commit_sha=commit_sha,
            state="succeeded",
            dry_run=dry_run,
            skipped=False,
            skipped_reason=None,
            registry_sync_required=not dry_run,
            projects=CountSummary(created=1, updated=0, deleted=0),
            components=CountSummary(created=2, updated=0, deleted=1),
            repositories=CountSummary(created=1, updated=0, deleted=0),
            edges=CountSummary(created=1, updated=0, deleted=0),
        )

    async def sync_registry(
        self, estate_key: str, *, dry_run: bool
    ) -> RegistrySyncSummary:
        """Record and return a fixed sync summary."""
        self.syncs.append({"estate_key": estate_key, "dry_run": dry_run})
        return RegistrySyncSummary(
            estate_key=estate_key,
            state="succeeded",
            dry_run=dry_run,
            repositories_created=1,
            repositories_updated=2,
            repositories_deactivated=0,
            repositories_conflicted=("other/estate-repo",),
            repositories_left_disabled=("org/alpha",),
            repositories_left_disabled_count=1,
        )

    async def list_repositories(
        self, estate_key: str, query: RepositoryQuery
    ) -> RepositoryPage:
        """Record and return the configured repository page."""
        self.repository_queries.append(query)
        return RepositoryPage(
            estate_key=estate_key,
            items=self.repository_items,
            limit=query.limit,
            offset=query.offset,
            has_more=False,
            next_offset=None,
        )

    async def set_ingestion(
        self, owner: str, name: str, *, enabled: bool
    ) -> IngestionToggleOutcome:
        """Record and return a fixed toggle outcome."""
        self.toggles.append({"owner": owner, "name": name, "enabled": enabled})
        return IngestionToggleOutcome(
            owner=owner,
            name=name,
            ingestion_enabled=enabled,
            changed=True,
        )


def _client(service: FakeEstateManagement) -> falcon.testing.TestClient:
    """Build a client for an app with only the estate service configured."""
    return falcon.testing.TestClient(
        create_app(AppDependencies(estate_service=service))
    )


@pytest.fixture
def service() -> FakeEstateManagement:
    """Return a fresh fake port."""
    return FakeEstateManagement()


@pytest.fixture
def client(service: FakeEstateManagement) -> falcon.testing.TestClient:
    """Build a client over the fake port."""
    return _client(service)


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

    async def oversize() -> typ.AsyncIterator[bytes]:
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
# GET /estates/{estate_key}/repositories
# ---------------------------------------------------------------------------


def test_list_repositories_returns_the_documented_envelope(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """Repository items carry exactly the documented fields."""
    result = client.simulate_get("/estates/demo/repositories")

    assert result.status_code == 200, "expected 200 from repositories"
    assert service.repository_queries == [RepositoryQuery()], "default query expected"
    assert result.json == {
        "estate_key": "demo",
        "items": [
            {
                "owner": "org",
                "name": "alpha",
                "default_branch": "main",
                "ingestion_enabled": True,
                "documentation_paths": list(_DOCUMENTATION_PATHS),
            }
        ],
        "limit": 50,
        "offset": 0,
        "has_more": False,
        "next_offset": None,
    }, "documented repository envelope expected"


def test_list_repositories_parses_every_query_parameter(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """The filter and pagination parameters reach the port."""
    result = client.simulate_get(
        "/estates/demo/repositories",
        params={
            "ingestion_enabled": "false",
            "limit": "5",
            "offset": "10",
        },
    )

    assert result.status_code == 200, "expected 200 from repositories"
    assert service.repository_queries == [
        RepositoryQuery(ingestion_enabled=False, limit=5, offset=10)
    ], "filters and paging should reach the service"
    assert result.json["limit"] == 5, "limit should echo the request"
    assert result.json["offset"] == 10, "offset should echo the request"


def test_list_repositories_accepts_no_filter(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """Omitting the filter lists both enabled and disabled repositories."""
    result = client.simulate_get("/estates/demo/repositories")

    assert result.status_code == 200, "expected 200 from repositories"
    assert service.repository_queries[0].ingestion_enabled is None, "no filter expected"


@pytest.mark.parametrize("value", ["yes", "1", "TRUE", ""])
def test_list_repositories_rejects_a_non_boolean_filter(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
    value: str,
) -> None:
    """The ingestion filter accepts exactly ``true`` or ``false``."""
    result = client.simulate_get(
        "/estates/demo/repositories", params={"ingestion_enabled": value}
    )

    assert result.status_code == 400, "expected 400 for a bad boolean"
    assert result.json["code"] == "invalid_input", "code should be invalid_input"
    assert result.json["field"] == "ingestion_enabled", "error should name the filter"
    assert service.repository_queries == [], "invalid input should not reach the port"


def test_list_repositories_rejects_a_repeated_filter(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """A repeated filter is ambiguous and rejected."""
    result = client.simulate_get(
        "/estates/demo/repositories?ingestion_enabled=true&ingestion_enabled=false"
    )

    assert result.status_code == 400, "expected 400 for a bad boolean"
    assert result.json["code"] == "invalid_input", "code should be invalid_input"
    assert result.json["field"] == "ingestion_enabled", "error should name the filter"
    assert service.repository_queries == [], "invalid input should not reach the port"


# ---------------------------------------------------------------------------
# PATCH /repositories/{owner}/{name}/ingestion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "application/merge-patch+json"],
)
def test_toggle_accepts_both_json_media_types(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
    content_type: str,
) -> None:
    """Both documented media types decode the same body."""
    result = client.simulate_patch(
        "/repositories/org/alpha/ingestion",
        body=b'{"ingestion_enabled": false}',
        headers={"Content-Type": content_type},
    )

    assert result.status_code == 200, "expected 200 from a toggle"
    assert service.toggles == [{"owner": "org", "name": "alpha", "enabled": False}], (
        "toggle arguments should reach the service"
    )
    assert result.json == {
        "owner": "org",
        "name": "alpha",
        "ingestion_enabled": False,
        "changed": True,
    }, "documented toggle envelope expected"


@pytest.mark.parametrize("body", [b"{}", b'{"ingestion_enabled": null}'])
def test_toggle_rejects_a_missing_or_null_flag(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
    body: bytes,
) -> None:
    """A missing or null flag is invalid input."""
    result = client.simulate_patch(
        "/repositories/org/alpha/ingestion",
        body=body,
        headers={"Content-Type": "application/json"},
    )

    assert result.status_code == 400, "expected 400 for a missing flag"
    assert result.json["code"] == "invalid_input", "code should be invalid_input"
    assert service.toggles == [], "invalid input should not reach the service"


@pytest.mark.parametrize(
    "body",
    [
        b'{"ingestion_enabled": 1}',
        b'{"ingestion_enabled": "true"}',
        b'{"ingestion_enabled": true, "extra": 1}',
    ],
)
def test_toggle_rejects_non_boolean_or_unknown_fields(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
    body: bytes,
) -> None:
    """The toggle body is strict about types and unknown fields."""
    result = client.simulate_patch(
        "/repositories/org/alpha/ingestion",
        body=body,
        headers={"Content-Type": "application/json"},
    )

    assert result.status_code == 400, "expected 400 for a bad toggle body"
    assert result.json["code"] == "invalid_input", "code should be invalid_input"
    assert service.toggles == [], "invalid input should not reach the service"


def test_toggle_rejects_an_unsupported_media_type(
    client: falcon.testing.TestClient,
    service: FakeEstateManagement,
) -> None:
    """A patch with an unsupported media type is a 415."""
    result = client.simulate_patch(
        "/repositories/org/alpha/ingestion",
        body=b"ingestion_enabled=false",
        headers={"Content-Type": "text/plain"},
    )

    assert result.status_code == 415, "expected 415 for a text body"
    assert result.json["code"] == "unsupported_media_type", "unsupported media type"
    assert service.toggles == [], "invalid input should not reach the service"


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
