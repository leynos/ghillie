"""Unit tests for the operator CLI command tree."""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    from cyclopts import App

from ghillie.cli.app import app


def _command_names(command_app: App) -> set[str]:
    return {
        str(item)
        for item in command_app
        if isinstance(item, str) and not item.startswith("-")
    }


def test_app_has_expected_name() -> None:
    """The packaged CLI should present itself as `ghillie`."""
    assert app.name == ("ghillie",)


def test_app_has_expected_root_nouns() -> None:
    """The root noun set should match the MVP CLI contract exactly."""
    assert _command_names(app) == {
        "estate",
        "export",
        "ingest",
        "metrics",
        "report",
        "stack",
    }


def test_stack_noun_has_expected_verbs() -> None:
    """The stack noun should expose the documented lifecycle verbs."""
    assert _command_names(app["stack"]) == {"down", "logs", "status", "up"}


def test_estate_noun_has_expected_verbs_and_repo_group() -> None:
    """The estate noun should include direct verbs and the nested repo group."""
    assert _command_names(app["estate"]) == {"import", "list", "repo", "sync"}
    assert _command_names(app["estate"]["repo"]) == {"list", "set"}


def test_other_nouns_have_expected_verbs() -> None:
    """The remaining nouns should match the documented verbs."""
    assert _command_names(app["ingest"]) == {"run", "status", "watch"}
    assert _command_names(app["export"]) == {
        "bundle",
        "events",
        "evidence",
        "reports",
    }
    assert _command_names(app["report"]) == {"run", "status", "watch"}
    assert _command_names(app["metrics"]) == {"nice", "required"}
