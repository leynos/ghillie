"""End-to-end estate-management journey through the packaged runtime.

The test starts a real ``ghillie.runtime`` process, drives the full operator
journey with the CLI module entry point and once through the installed console
script, then checks each endpoint directly with raw HTTP so the wire contract
is proven independently of the CLI.
"""

from __future__ import annotations

import json
import sys
import typing as typ
from pathlib import Path

import httpx
import pytest

from tests.e2e.conftest import REPO_ROOT, CliResult, GhillieServer, run_cli

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(120)]

_CATALOGUE = REPO_ROOT / "examples" / "wildside-catalogue.yaml"


def _document(result: CliResult) -> dict[str, object]:
    """Parse a successful JSON result, failing with the streams otherwise."""
    assert result.returncode == 0, result.detail()
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict), f"expected a JSON object, got {parsed!r}"
    return typ.cast("dict[str, object]", parsed)


def _items(document: dict[str, object]) -> list[dict[str, object]]:
    """Return the ``items`` array of a collection document."""
    items = document.get("items")
    assert isinstance(items, list), f"expected items, got {document!r}"
    return [typ.cast("dict[str, object]", item) for item in items]


def _has_repository(
    document: dict[str, object],
    owner: str,
    name: str,
) -> bool:
    """Return whether *document* lists ``owner/name``."""
    return any(
        item.get("owner") == owner and item.get("name") == name
        for item in _items(document)
    )


def _console_script() -> Path:
    """Return the installed ``ghillie`` console script next to the interpreter."""
    script = Path(sys.executable).parent / "ghillie"
    assert script.exists(), f"console script missing at {script}"
    return script


def _import_catalogue(
    server: GhillieServer,
    commit_sha: str,
    *,
    output: str | None = None,
) -> CliResult:
    """Run one catalogue import for the journey's estate."""
    prefix = [] if output is None else ["--output", output]
    return run_cli(
        server,
        *prefix,
        "estate",
        "import",
        "--estate-key",
        "demo",
        "--catalogue-path",
        str(_CATALOGUE),
        "--commit-sha",
        commit_sha,
    )


def _sync_registry(server: GhillieServer) -> dict[str, object]:
    """Sync the journey's estate and return the JSON document."""
    return _document(
        run_cli(server, "--output", "json", "estate", "sync", "--estate-key", "demo")
    )


def _list_repositories(server: GhillieServer, state_flag: str) -> dict[str, object]:
    """List the journey's repositories through *state_flag* as JSON."""
    return _document(
        run_cli(
            server,
            "--output",
            "json",
            "estate",
            "repo",
            "list",
            "--estate-key",
            "demo",
            state_flag,
        )
    )


def _toggle_ingestion(server: GhillieServer) -> dict[str, object]:
    """Disable ingestion for the journey's repository and return the document."""
    return _document(
        run_cli(
            server,
            "--output",
            "json",
            "estate",
            "repo",
            "set",
            "--owner",
            "leynos",
            "--name",
            "wildside",
            "--ingestion-disabled",
        )
    )


def test_estate_management_journey(ghillie_server: GhillieServer) -> None:
    """Drive import, sync, toggle, re-sync, and the raw wire contract."""
    server = ghillie_server

    imported = _import_catalogue(server, "c1")
    assert imported.returncode == 0, imported.detail()
    assert "repositories.created: " in imported.stdout, imported.detail()

    estates = _document(run_cli(server, "--output", "json", "estate", "list"))
    assert any(item.get("key") == "demo" for item in _items(estates)), estates

    sync = _sync_registry(server)
    assert sync.get("state") == "succeeded", sync

    active = _list_repositories(server, "--active")
    assert _has_repository(active, "leynos", "wildside"), active

    toggled = _toggle_ingestion(server)
    assert toggled.get("ingestion_enabled") is False, toggled
    assert toggled.get("changed") is True, toggled

    reimported = _document(_import_catalogue(server, "c2", output="json"))
    assert reimported.get("skipped") is False, reimported

    resync = _sync_registry(server)
    left_disabled = resync.get("repositories_left_disabled")
    assert isinstance(left_disabled, list), resync
    assert "leynos/wildside" in left_disabled, resync

    inactive = _list_repositories(server, "--inactive")
    assert _has_repository(inactive, "leynos", "wildside"), inactive

    console = run_cli(
        server,
        "--output",
        "json",
        "estate",
        "list",
        executable=[str(_console_script())],
    )
    assert console.returncode == 0, console.detail()

    _assert_wire_contract(server)


def _assert_wire_contract(server: GhillieServer) -> None:
    """Exercise each estate endpoint directly, independent of the CLI."""
    catalogue_yaml = _CATALOGUE.read_text(encoding="utf-8")
    with httpx.Client(base_url=server.base_url, timeout=10.0) as client:
        estates = client.get("/estates")
        assert estates.status_code == 200, estates.text
        assert estates.json()["items"], estates.text

        imported = client.post(
            "/estates/demo/catalogue-import",
            json={"commit_sha": "c3", "catalogue_yaml": catalogue_yaml},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["skipped"] is False, imported.text

        synced = client.post("/estates/demo/registry-sync")
        assert synced.status_code == 200, synced.text
        assert synced.json()["state"] == "succeeded", synced.text

        repositories = client.get("/estates/demo/repositories")
        assert repositories.status_code == 200, repositories.text
        assert any(
            item["owner"] == "leynos" and item["name"] == "wildside"
            for item in repositories.json()["items"]
        ), repositories.text

        toggled = client.patch(
            "/repositories/leynos/wildside/ingestion",
            json={"ingestion_enabled": True},
        )
        assert toggled.status_code == 200, toggled.text
        assert toggled.json()["ingestion_enabled"] is True, toggled.text

        missing = client.get("/estates/missing/repositories")
        assert missing.status_code == 404, missing.text
        assert missing.json()["code"] == "estate_not_found", missing.text
