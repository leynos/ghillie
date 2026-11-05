"""Syrupy snapshots of operator-facing estate output.

Table output is explicitly not a contract (D7), so these snapshots are the
record of what an operator sees and change deliberately. JSON is compared by
parsed equality elsewhere; here the YAML and table forms are pinned.
"""

from __future__ import annotations

import json
import typing as typ

from ghillie.cli.commands.estate import (
    import_catalogue,
    list_estates,
    list_repositories,
    set_repository,
    sync,
)
from ghillie.cli.control_plane import (
    ControlPlaneError,
    ControlPlaneIssue,
    ControlPlaneResponse,
)
from ghillie.cli.output import render_error

if typ.TYPE_CHECKING:
    from pathlib import Path

    from tests.unit.cli.harness import CliHarness

_ESTATE_PAYLOAD: dict[str, object] = {
    "items": [
        {
            "key": "demo",
            "name": "Demo Estate",
            "description": "Example estate",
            "last_import": {
                "commit_sha": "c1",
                "imported_at": "2026-11-05T09:30:00+00:00",
            },
        },
        {
            "key": "ops",
            "name": "Operations",
            "description": None,
            "last_import": None,
        },
    ],
    "limit": 50,
    "offset": 0,
    "has_more": False,
    "next_offset": None,
}

_REPOSITORY_PAYLOAD: dict[str, object] = {
    "estate_key": "demo",
    "items": [
        {
            "owner": "leynos",
            "name": "wildside",
            "default_branch": "main",
            "ingestion_enabled": True,
            "documentation_paths": ["docs/"],
        },
        {
            "owner": "leynos",
            "name": "ghillie",
            "default_branch": "trunk",
            "ingestion_enabled": False,
            "documentation_paths": [],
        },
    ],
    "limit": 50,
    "offset": 0,
    "has_more": True,
    "next_offset": 2,
}

_IMPORT_PAYLOAD: dict[str, object] = {
    "estate_key": "demo",
    "commit_sha": "c1",
    "state": "succeeded",
    "dry_run": False,
    "skipped": False,
    "skipped_reason": None,
    "registry_sync_required": True,
    "projects": {"created": 1, "updated": 0, "deleted": 0},
    "components": {"created": 2, "updated": 0, "deleted": 0},
    "repositories": {"created": 1, "updated": 0, "deleted": 0},
    "edges": {"created": 0, "updated": 0, "deleted": 0},
}

_SYNC_PAYLOAD: dict[str, object] = {
    "estate_key": "demo",
    "state": "succeeded",
    "dry_run": False,
    "repositories_created": 1,
    "repositories_updated": 0,
    "repositories_deactivated": 0,
    "repositories_conflicted": [],
    "repositories_left_disabled": ["leynos/wildside"],
    "repositories_left_disabled_count": 1,
}

_TOGGLE_PAYLOAD: dict[str, object] = {
    "owner": "leynos",
    "name": "wildside",
    "ingestion_enabled": False,
    "changed": True,
}


def test_estate_list_table_snapshot(
    harness: typ.Callable[..., CliHarness],
    snapshot: object,
) -> None:
    """The estate table stays readable for a missing description and import."""
    client = harness()
    client.queue_json(_ESTATE_PAYLOAD)

    result = client.invoke(list_estates)

    assert result == snapshot


def test_estate_list_yaml_snapshot(
    harness: typ.Callable[..., CliHarness],
    snapshot: object,
) -> None:
    """YAML is the server envelope, which is the contract."""
    client = harness(output="yaml")
    client.queue_json(_ESTATE_PAYLOAD)

    result = client.invoke(list_estates)

    assert result == snapshot


def _repository_listing(
    harness: typ.Callable[..., CliHarness], *, output: str
) -> object:
    """Render the fixed repository page in *output* for a snapshot comparison."""
    client = harness(output=output)
    client.queue_json(_REPOSITORY_PAYLOAD)
    return client.invoke(
        list_repositories,
        estate_key="demo",
        ingestion_enabled=None,
        limit=50,
        offset=0,
    )


def test_repository_list_table_snapshot(
    harness: typ.Callable[..., CliHarness],
    snapshot: object,
) -> None:
    """The repository table shows the ingestion state and page cursor."""
    assert _repository_listing(harness, output="table") == snapshot


def test_repository_list_yaml_snapshot(
    harness: typ.Callable[..., CliHarness],
    snapshot: object,
) -> None:
    """Repository YAML keeps ``estate_key`` and the pagination metadata."""
    assert _repository_listing(harness, output="yaml") == snapshot


def test_import_table_snapshot(
    harness: typ.Callable[..., CliHarness],
    catalogue_file: Path,
    snapshot: object,
) -> None:
    """Import output flattens the count families into named fields."""
    client = harness()
    client.queue_json(_IMPORT_PAYLOAD)

    result = client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=catalogue_file,
        commit_sha="c1",
        estate_name=None,
    )

    assert result == snapshot


def test_skipped_import_table_snapshot(
    harness: typ.Callable[..., CliHarness],
    catalogue_file: Path,
    snapshot: object,
) -> None:
    """A skipped import is announced before the summary."""
    client = harness()
    client.queue_json(
        {
            **_IMPORT_PAYLOAD,
            "skipped": True,
            "skipped_reason": "commit_already_imported",
            "registry_sync_required": False,
        }
    )

    result = client.invoke(
        import_catalogue,
        estate_key="demo",
        catalogue_path=catalogue_file,
        commit_sha="c1",
        estate_name=None,
    )

    assert result == snapshot


def test_sync_table_snapshot(
    harness: typ.Callable[..., CliHarness],
    snapshot: object,
) -> None:
    """Sync shows the counts and the repositories left disabled."""
    client = harness()
    client.queue_json(_SYNC_PAYLOAD)

    result = client.invoke(sync, estate_key="demo")

    assert result == snapshot


def test_toggle_table_snapshot(
    harness: typ.Callable[..., CliHarness],
    snapshot: object,
) -> None:
    """A toggle reports the resulting state and whether it changed."""
    client = harness()
    client.queue_json(_TOGGLE_PAYLOAD)

    result = client.invoke(
        set_repository,
        owner="leynos",
        name="wildside",
        ingestion_enabled=False,
    )

    assert result == snapshot


def _error() -> ControlPlaneError:
    return ControlPlaneError(
        "catalogue_invalid",
        "catalogue validation failed",
        hint="Fix the listed catalogue issues and import the catalogue again.",
        response=ControlPlaneResponse(
            422,
            (
                ControlPlaneIssue("catalogue_schema", "projects: 42 is not a list"),
                ControlPlaneIssue("catalogue_schema", "component key 'x' is invalid"),
            ),
        ),
    )


def test_error_table_snapshot(snapshot: object) -> None:
    """The readable error form stays stable."""
    assert render_error(_error(), output="table") == snapshot


def test_error_yaml_snapshot(snapshot: object) -> None:
    """The YAML error form stays stable."""
    assert render_error(_error(), output="yaml") == snapshot


def test_error_json_matches_the_documented_envelope() -> None:
    """JSON errors are compared structurally, not as text."""
    parsed = json.loads(render_error(_error(), output="json"))

    assert parsed == {
        "error": {
            "code": "catalogue_invalid",
            "message": "catalogue validation failed",
            "hint": "Fix the listed catalogue issues and import the catalogue again.",
            "status": 422,
            "issues": [
                {"code": "catalogue_schema", "message": "projects: 42 is not a list"},
                {
                    "code": "catalogue_schema",
                    "message": "component key 'x' is invalid",
                },
            ],
        }
    }
