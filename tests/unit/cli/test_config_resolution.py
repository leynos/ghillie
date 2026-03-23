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


@pytest.mark.parametrize(
    ("options", "env", "match"),
    [
        pytest.param(
            GlobalOptions(api_base_url="ftp://example.com"),
            {},
            "api_base_url",
            id="invalid_scheme",
        ),
        pytest.param(
            GlobalOptions(api_base_url="http://"),
            {},
            "api_base_url",
            id="missing_netloc",
        ),
        pytest.param(
            GlobalOptions(),
            {"GHILLIE_REQUEST_TIMEOUT_S": "abc"},
            "request_timeout_s",
            id="invalid_request_timeout_env",
        ),
        pytest.param(
            GlobalOptions(),
            {"GHILLIE_OUTPUT": "xml"},
            "output",
            id="invalid_output_env",
        ),
        pytest.param(
            GlobalOptions(),
            {"GHILLIE_LOG_LEVEL": "verbose"},
            "log_level",
            id="invalid_log_level_env",
        ),
        pytest.param(
            GlobalOptions(),
            {"GHILLIE_NON_INTERACTIVE": "definitely-not-a-bool"},
            r"non_interactive|dry_run",
            id="invalid_non_interactive_env",
        ),
        pytest.param(
            GlobalOptions(),
            {"GHILLIE_DRY_RUN": "definitely-not-a-bool"},
            r"non_interactive|dry_run",
            id="invalid_dry_run_env",
        ),
    ],
)
def test_config_invalid_value_raises_value_error(
    tmp_path: Path,
    options: GlobalOptions,
    env: dict[str, str],
    match: str,
) -> None:
    """Invalid configuration values should raise ValueError."""
    with pytest.raises(ValueError, match=match):
        resolve_cli_config(
            options,
            env=env,
            profile_path=tmp_path / "cli.toml",
            state_path=tmp_path / "state.json",
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


@pytest.mark.parametrize(
    ("state_content", "profile_content", "match"),
    [
        pytest.param(
            "[]",
            None,
            r"state\.json must contain a JSON object",
            id="non_object_state_json",
        ),
        pytest.param(
            None,
            'global = "oops"\n',
            r"\[global\] section.*must be a table",
            id="non_table_global_section",
        ),
    ],
)
def test_config_invalid_file_content_raises_type_error(
    tmp_path: Path,
    state_content: str | None,
    profile_content: str | None,
    match: str,
) -> None:
    """Malformed profile or state file content should raise TypeError."""
    profile_path = tmp_path / "cli.toml"
    state_path = tmp_path / "state.json"
    if state_content is not None:
        state_path.write_text(state_content, encoding="utf-8")
    if profile_content is not None:
        profile_path.write_text(profile_content, encoding="utf-8")

    with pytest.raises(TypeError, match=match):
        resolve_cli_config(
            GlobalOptions(),
            env={},
            profile_path=profile_path,
            state_path=state_path,
        )
