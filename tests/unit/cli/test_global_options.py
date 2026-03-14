"""Unit tests for global option parsing and command context construction."""

from __future__ import annotations

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
