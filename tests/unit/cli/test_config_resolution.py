"""Unit tests for CLI configuration precedence."""

from __future__ import annotations

import json
import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path

from ghillie.cli.config import GlobalOptions, resolve_cli_config


def _write_profile(path: Path) -> None:
    path.write_text(
        """
[global]
api_base_url = "http://127.0.0.1:7000"
auth_token_env = "PROFILE_AUTH_TOKEN"
output = "yaml"
log_level = "warn"
request_timeout_s = 18.5
non_interactive = true
dry_run = false
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_state(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "api_base_url": "http://127.0.0.1:7100",
                "source": "stack_up",
                "updated_at": "2026-03-14T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def test_config_precedence_is_flag_env_profile_state_then_fallback(
    tmp_path: Path,
) -> None:
    """The documented precedence order should resolve the effective API URL."""
    profile_path = tmp_path / "cli.toml"
    state_path = tmp_path / "state.json"
    _write_profile(profile_path)
    _write_state(state_path)

    config = resolve_cli_config(
        GlobalOptions(api_base_url="http://127.0.0.1:7200"),
        env={
            "GHILLIE_API_BASE_URL": "http://127.0.0.1:7300",
            "GHILLIE_OUTPUT": "json",
            "PROFILE_AUTH_TOKEN": "profile-token",
        },
        profile_path=profile_path,
        state_path=state_path,
    )

    assert config.api_base_url == "http://127.0.0.1:7200"
    assert config.api_base_url_source == "flag"
    assert config.output == "json"
    assert config.auth_token == "profile-token"  # noqa: S105
    assert config.log_level == "warn"
    assert config.request_timeout_s == 18.5


def test_config_uses_state_then_fallback_when_higher_sources_absent(
    tmp_path: Path,
) -> None:
    """Persisted runtime state should beat fallback when no higher source exists."""
    state_path = tmp_path / "state.json"
    _write_state(state_path)

    from_state = resolve_cli_config(
        GlobalOptions(),
        env={},
        profile_path=tmp_path / "missing.toml",
        state_path=state_path,
    )
    from_fallback = resolve_cli_config(
        GlobalOptions(),
        env={},
        profile_path=tmp_path / "missing.toml",
        state_path=tmp_path / "missing.json",
    )

    assert from_state.api_base_url == "http://127.0.0.1:7100"
    assert from_state.api_base_url_source == "state"
    assert from_fallback.api_base_url == "http://127.0.0.1:8080"
    assert from_fallback.api_base_url_source == "fallback"
