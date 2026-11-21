"""End-to-end estate-management journey over the packaged HTTP API.

Each test starts a real ``ghillie.runtime`` process against a fresh SQLite
database. That proves the ASGI lifespan creates the schema, that a configured
bearer token guards the estate routes while leaving the probes open, and that
an import, a registry sync and an ingestion toggle each survive to a later
read in a separate request.
"""

from __future__ import annotations

import http
import typing as typ

import httpx
import pytest

from tests.e2e.conftest import REPO_ROOT, GhillieServer

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(120)]

_CATALOGUE = REPO_ROOT / "examples" / "wildside-catalogue.yaml"


def _items(document: dict[str, typ.Any]) -> list[dict[str, typ.Any]]:
    """Return the ``items`` array of a collection document."""
    items = document["items"]
    assert isinstance(items, list), f"expected items, got {document!r}"
    return [typ.cast("dict[str, typ.Any]", item) for item in items]


def _repository(
    document: dict[str, typ.Any],
    owner: str,
    name: str,
) -> dict[str, typ.Any] | None:
    """Return the ``owner/name`` entry of a repository collection, if listed."""
    return next(
        (
            item
            for item in _items(document)
            if item.get("owner") == owner and item.get("name") == name
        ),
        None,
    )


def test_probes_answer_without_credentials(ghillie_server: GhillieServer) -> None:
    """The liveness and readiness probes stay open when a token is configured."""
    with httpx.Client(
        base_url=ghillie_server.base_url, timeout=5.0
    ) as anonymous_client:
        health = anonymous_client.get("/health")
        ready = anonymous_client.get("/ready")

    assert health.status_code == http.HTTPStatus.OK, health.text
    assert ready.status_code == http.HTTPStatus.OK, ready.text


def test_estate_routes_reject_missing_credentials(
    ghillie_server: GhillieServer,
) -> None:
    """An unauthenticated estate request gets the shared error envelope."""
    with httpx.Client(
        base_url=ghillie_server.base_url, timeout=5.0
    ) as anonymous_client:
        response = anonymous_client.get("/estates")

    assert response.status_code == http.HTTPStatus.UNAUTHORIZED, response.text
    assert response.json()["code"] == "unauthorized", response.text


def test_estate_management_journey(ghillie_server: GhillieServer) -> None:
    """Import, list, sync and toggle over HTTP, then read the state back."""
    catalogue_yaml = _CATALOGUE.read_text(encoding="utf-8")
    with ghillie_server.client() as client:
        imported = client.post(
            "/estates/demo/catalogue-import",
            json={"commit_sha": "c1", "catalogue_yaml": catalogue_yaml},
        )
        assert imported.status_code == http.HTTPStatus.OK, imported.text
        assert imported.json()["skipped"] is False, imported.text

        estates = client.get("/estates")
        assert estates.status_code == http.HTTPStatus.OK, estates.text
        assert [item.get("key") for item in _items(estates.json())] == ["demo"], (
            estates.text
        )

        synced = client.post("/estates/demo/registry-sync")
        assert synced.status_code == http.HTTPStatus.OK, synced.text
        assert synced.json()["state"] == "succeeded", synced.text

        listed = client.get("/estates/demo/repositories")
        assert listed.status_code == http.HTTPStatus.OK, listed.text
        registered = _repository(listed.json(), "leynos", "wildside")
        assert registered is not None, listed.text
        # The toggle below is only a transition if it starts enabled.
        assert registered["ingestion_enabled"] is True, listed.text

        toggled = client.patch(
            "/repositories/leynos/wildside/ingestion",
            json={"ingestion_enabled": False},
        )
        assert toggled.status_code == http.HTTPStatus.OK, toggled.text
        assert toggled.json()["ingestion_enabled"] is False, toggled.text
        assert toggled.json()["changed"] is True, toggled.text

    # A second client proves the toggle outlived the request that wrote it.
    with ghillie_server.client() as client:
        reread = client.get("/estates/demo/repositories")
        assert reread.status_code == http.HTTPStatus.OK, reread.text
        persisted = _repository(reread.json(), "leynos", "wildside")
        assert persisted is not None, reread.text
        assert persisted["ingestion_enabled"] is False, reread.text
