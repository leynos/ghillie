"""HTTP resource behaviour for repository listing and ingestion toggles.

Estate listing, import, and synchronization live in
``test_api_estate_resources.py``. These resources share the same fake port, so
the transport contract stays in one place per endpoint family.
"""

import typing as typ

import pytest

from ghillie.estate.models import RepositoryQuery
from tests.unit.estate_test_helpers import (
    DOCUMENTATION_PATHS,
    FakeEstateManagement,
    build_estate_client,
)

if typ.TYPE_CHECKING:
    import falcon.testing


@pytest.fixture
def service() -> FakeEstateManagement:
    """Return a fresh fake port."""
    return FakeEstateManagement()


@pytest.fixture
def client(service: FakeEstateManagement) -> falcon.testing.TestClient:
    """Build a client over the fake port."""
    return build_estate_client(service)


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
                "documentation_paths": list(DOCUMENTATION_PATHS),
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
