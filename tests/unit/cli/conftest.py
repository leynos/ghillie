"""Fixtures shared by the CLI unit tests."""

from __future__ import annotations

import typing as typ

import pytest

from tests.unit.cli.harness import BASE_URL, CliHarness


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> typ.Callable[..., CliHarness]:
    """Return a factory that builds a harness with the given options."""

    def build(
        *,
        output: str = "table",
        dry_run: bool = False,
        api_base_url: str = BASE_URL,
        auth_token: str | None = None,
    ) -> CliHarness:
        return CliHarness(
            monkeypatch,
            output=output,
            dry_run=dry_run,
            api_base_url=api_base_url,
            auth_token=auth_token,
        )

    return build
