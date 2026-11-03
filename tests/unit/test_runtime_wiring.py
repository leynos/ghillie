"""Runtime environment wiring for the estate API (D13 and D14).

The runtime must expose estate routes whenever a database is configured,
expose report routes only when a status backend is also configured, read the
optional API token, and fail fast on an unknown bootstrap value.
"""

from __future__ import annotations

import typing as typ

import falcon.asgi
import falcon.testing
import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path


def _set_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the runtime at an empty SQLite database."""
    monkeypatch.setenv(
        "GHILLIE_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
    )
    monkeypatch.delenv("GHILLIE_STATUS_MODEL_BACKEND", raising=False)
    monkeypatch.delenv("GHILLIE_DB_BOOTSTRAP", raising=False)
    monkeypatch.delenv("GHILLIE_API_TOKEN", raising=False)


def _client() -> falcon.testing.TestClient:
    """Build a client for the runtime app."""
    from ghillie.runtime import create_app

    return falcon.testing.TestClient(create_app())


def test_estate_routes_need_only_a_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A database URL alone exposes estates and not reports."""
    _set_database(monkeypatch, tmp_path)

    client = _client()

    estates = client.simulate_get("/estates")
    assert estates.status_code == 503
    assert estates.json["code"] == "storage_unavailable"
    assert client.simulate_post("/reports/repositories/acme/widgets").status_code == 404


def test_reporting_route_needs_a_status_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A status backend adds report routes alongside estate routes."""
    _set_database(monkeypatch, tmp_path)
    monkeypatch.setenv("GHILLIE_STATUS_MODEL_BACKEND", "mock")

    client = _client()

    assert client.simulate_get("/estates").status_code == 503
    assert client.simulate_post("/reports/repositories/acme/widgets").status_code != 404


def test_invalid_bootstrap_value_fails_fast(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unknown ``GHILLIE_DB_BOOTSTRAP`` value stops start-up."""
    _set_database(monkeypatch, tmp_path)
    monkeypatch.setenv("GHILLIE_DB_BOOTSTRAP", "drop-all")

    from ghillie.runtime import create_app

    with pytest.raises(SystemExit):
        create_app()


def test_create_all_bootstrap_value_is_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The documented bootstrap value builds the app."""
    _set_database(monkeypatch, tmp_path)
    monkeypatch.setenv("GHILLIE_DB_BOOTSTRAP", "create-all")

    from ghillie.runtime import create_app

    assert isinstance(create_app(), falcon.asgi.App)


def test_api_token_from_environment_protects_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The runtime reads ``GHILLIE_API_TOKEN`` into the auth middleware."""
    _set_database(monkeypatch, tmp_path)
    monkeypatch.setenv("GHILLIE_API_TOKEN", "runtime-token")

    client = _client()

    assert client.simulate_get("/estates").status_code == 401
    assert (
        client.simulate_get(
            "/estates", headers={"Authorization": "Bearer runtime-token"}
        ).status_code
        == 503
    )
