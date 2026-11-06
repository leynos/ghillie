"""Server payloads shared by the estate CLI command tests.

The fake control plane answers every verb with a document shaped like the
service's response, so one copy of each payload keeps the wire contract tests
from drifting apart.
"""

from __future__ import annotations

import json
import typing as typ

IMPORT_PAYLOAD: dict[str, object] = {
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

SYNC_PAYLOAD: dict[str, object] = {
    "estate_key": "demo",
    "state": "succeeded",
    "dry_run": False,
    "repositories_created": 1,
    "repositories_updated": 0,
    "repositories_deactivated": 0,
    "repositories_conflicted": [],
    "repositories_left_disabled": [],
    "repositories_left_disabled_count": 0,
}

ESTATE_LIST_PAYLOAD: dict[str, object] = {
    "items": [
        {
            "key": "demo",
            "name": "Demo Estate",
            "description": "Example estate",
            "last_import": {
                "commit_sha": "c1",
                "imported_at": "2026-11-05T09:30:00+00:00",
            },
        }
    ],
    "limit": 50,
    "offset": 0,
    "has_more": False,
    "next_offset": None,
}

REPOSITORY_LIST_PAYLOAD: dict[str, object] = {
    "estate_key": "demo",
    "items": [
        {
            "owner": "leynos",
            "name": "wildside",
            "default_branch": "main",
            "ingestion_enabled": True,
            "documentation_paths": ["docs/"],
        }
    ],
    "limit": 10,
    "offset": 0,
    "has_more": False,
    "next_offset": None,
}

TOGGLE_PAYLOAD: dict[str, object] = {
    "owner": "leynos",
    "name": "wildside",
    "ingestion_enabled": False,
    "changed": True,
}


def error_document(standard_error: str) -> dict[str, typ.Any]:
    """Parse the structured error JSON the command wrote to standard error."""
    return typ.cast("dict[str, typ.Any]", json.loads(standard_error.strip()))
