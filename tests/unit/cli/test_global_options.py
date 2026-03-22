"""Unit tests for global option parsing and command context construction."""

from __future__ import annotations

import pytest

from ghillie.cli.app import main as cli_main
from ghillie.cli.app import parse_global_options
from ghillie.cli.config import GlobalOptions, resolve_cli_config


def test_parse_global_options_consumes_root_options_before_noun() -> None:
    """Known root options should be consumed before the noun command."""
    options, remaining = parse_global_options(
        [
            "--api-base-url",
            "http://127.0.0.1:9999",
            "--output=json",
            "--request-timeout-s",
            "12.5",
            "report",
            "run",
            "--help",
        ]
    )

    assert options == GlobalOptions(
        api_base_url="http://127.0.0.1:9999",
        auth_token=None,
        output="json",
        log_level=None,
        request_timeout_s=12.5,
        non_interactive=None,
        dry_run=None,
    )
    assert remaining == ["report", "run", "--help"]


def test_resolved_cli_config_preserves_explicit_root_options() -> None:
    """Explicit root options should survive resolution into handler context."""
    config = resolve_cli_config(
        GlobalOptions(
            api_base_url="http://127.0.0.1:9999",
            auth_token="secret-token",  # noqa: S106
            output="yaml",
            log_level="debug",
            request_timeout_s=9.0,
            non_interactive=False,
            dry_run=True,
        ),
        env={},
    )

    assert config.api_base_url == "http://127.0.0.1:9999"
    assert config.api_base_url_source == "flag"
    assert config.auth_token == "secret-token"  # noqa: S105
    assert config.output == "yaml"
    assert config.log_level == "debug"
    assert config.request_timeout_s == 9.0
    assert config.non_interactive is False
    assert config.dry_run is True


def test_parse_global_options_boolean_toggles_and_inline_syntax() -> None:
    """Boolean toggles and inline value syntax should be parsed correctly."""
    # non-interactive + explicit no-dry-run, inline output value
    options, remaining = parse_global_options(
        [
            "--non-interactive",
            "--no-dry-run",
            "--output=json",
            "report",
        ]
    )

    assert options == GlobalOptions(
        api_base_url=None,
        auth_token=None,
        output="json",
        log_level=None,
        request_timeout_s=None,
        non_interactive=True,
        dry_run=False,
    )
    assert remaining == ["report"]

    # interactive cancels non-interactive, dry-run enabled, inline timeout
    options, remaining = parse_global_options(
        [
            "--interactive",
            "--dry-run",
            "--request-timeout-s=3.5",
            "report",
            "status",
        ]
    )

    assert options == GlobalOptions(
        api_base_url=None,
        auth_token=None,
        output=None,
        log_level=None,
        request_timeout_s=3.5,
        non_interactive=False,
        dry_run=True,
    )
    assert remaining == ["report", "status"]


def test_parse_global_options_raises_when_value_option_missing_value() -> None:
    """Value-bearing options without a value should raise ValueError."""
    with pytest.raises(ValueError, match="requires a value"):
        parse_global_options(["--api-base-url"])


def test_main_exits_with_code_2_on_invalid_request_timeout() -> None:
    """Invalid --request-timeout-s should cause main() to exit with code 2."""
    exit_code = cli_main(["--request-timeout-s", "abc", "report"])

    assert exit_code == 2
