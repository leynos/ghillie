"""Unit tests for CLI configuration precedence."""

from __future__ import annotations

import json
import typing as typ

import pytest

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


def test_config_invalid_api_base_url_scheme_raises_value_error(tmp_path: Path) -> None:
    """Non-HTTP(S) API URLs should be rejected."""
    profile_path = tmp_path / "cli.toml"
    state_path = tmp_path / "state.json"

    with pytest.raises(ValueError, match="api_base_url"):
        resolve_cli_config(
            GlobalOptions(api_base_url="ftp://example.com"),
            env={},
            profile_path=profile_path,
            state_path=state_path,
        )


def test_config_invalid_api_base_url_missing_netloc_raises_value_error(
    tmp_path: Path,
) -> None:
    """API URLs without netloc should be rejected."""
    profile_path = tmp_path / "cli.toml"
    state_path = tmp_path / "state.json"

    with pytest.raises(ValueError, match="api_base_url"):
        resolve_cli_config(
            GlobalOptions(api_base_url="http://"),
            env={},
            profile_path=profile_path,
            state_path=state_path,
        )


def test_config_invalid_request_timeout_env_raises_value_error(tmp_path: Path) -> None:
    """Non-numeric GHILLIE_REQUEST_TIMEOUT_S should raise ValueError."""
    profile_path = tmp_path / "cli.toml"
    state_path = tmp_path / "state.json"

    with pytest.raises(ValueError, match="request_timeout_s"):
        resolve_cli_config(
            GlobalOptions(),
            env={"GHILLIE_REQUEST_TIMEOUT_S": "abc"},
            profile_path=profile_path,
            state_path=state_path,
        )


def test_config_invalid_output_env_raises_value_error(tmp_path: Path) -> None:
    """Invalid GHILLIE_OUTPUT should raise ValueError."""
    profile_path = tmp_path / "cli.toml"
    state_path = tmp_path / "state.json"

    with pytest.raises(ValueError, match="output"):
        resolve_cli_config(
            GlobalOptions(),
            env={"GHILLIE_OUTPUT": "xml"},
            profile_path=profile_path,
            state_path=state_path,
        )


def test_config_invalid_log_level_env_raises_value_error(tmp_path: Path) -> None:
    """Invalid GHILLIE_LOG_LEVEL should raise ValueError."""
    profile_path = tmp_path / "cli.toml"
    state_path = tmp_path / "state.json"

    with pytest.raises(ValueError, match="log_level"):
        resolve_cli_config(
            GlobalOptions(),
            env={"GHILLIE_LOG_LEVEL": "verbose"},
            profile_path=profile_path,
            state_path=state_path,
        )


@pytest.mark.parametrize(
    "env_key",
    [
        "GHILLIE_NON_INTERACTIVE",
        "GHILLIE_DRY_RUN",
    ],
)
def test_config_invalid_bool_env_raises_value_error(
    tmp_path: Path, env_key: str
) -> None:
    """Non-boolean toggles in env should raise ValueError."""
    profile_path = tmp_path / "cli.toml"
    state_path = tmp_path / "state.json"

    with pytest.raises(ValueError, match=r"non_interactive|dry_run"):
        resolve_cli_config(
            GlobalOptions(),
            env={env_key: "definitely-not-a-bool"},
            profile_path=profile_path,
            state_path=state_path,
        )


def test_config_auth_token_resolution_with_missing_env_var(tmp_path: Path) -> None:
    """When auth_token_env points to unset env var, auth_token should be None."""
    profile_path = tmp_path / "cli.toml"
    state_path = tmp_path / "state.json"
    profile_path.write_text(
        """
[global]
auth_token_env = "MISSING_TOKEN"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = resolve_cli_config(
        GlobalOptions(),
        env={},
        profile_path=profile_path,
        state_path=state_path,
    )

    assert config.auth_token is None


def test_config_direct_auth_token_flag_overrides_env_and_profile(
    tmp_path: Path,
) -> None:
    """Direct auth_token flag overrides GHILLIE_AUTH_TOKEN and auth_token_env."""
    profile_path = tmp_path / "cli.toml"
    state_path = tmp_path / "state.json"
    profile_path.write_text(
        """
[global]
auth_token_env = "PROFILE_TOKEN"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = resolve_cli_config(
        GlobalOptions(auth_token="flag-token"),  # noqa: S106
        env={
            "GHILLIE_AUTH_TOKEN": "env-token",
            "PROFILE_TOKEN": "profile-env-token",
        },
        profile_path=profile_path,
        state_path=state_path,
    )

    assert config.auth_token == "flag-token"  # noqa: S105
