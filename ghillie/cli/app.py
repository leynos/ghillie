"""Root app and entry-point helpers for the packaged operator CLI."""

from __future__ import annotations

import os
import sys
import typing as typ

from cyclopts import App
from cyclopts.exceptions import CycloptsError

from ghillie.cli.commands.estate import estate_app
from ghillie.cli.commands.export import export_app
from ghillie.cli.commands.ingest import ingest_app
from ghillie.cli.commands.metrics import metrics_app
from ghillie.cli.commands.report import report_app
from ghillie.cli.commands.stack import stack_app
from ghillie.cli.config import GlobalOptions, resolve_cli_config
from ghillie.cli.context import CommandContext, use_context

_OPTION_REQUIRES_VALUE = {
    "--api-base-url": "api_base_url",
    "--auth-token": "auth_token",
    "--output": "output",
    "--log-level": "log_level",
    "--request-timeout-s": "request_timeout_s",
}
_BOOLEAN_OPTION_VALUES = {
    "--non-interactive": ("non_interactive", True),
    "--interactive": ("non_interactive", False),
    "--dry-run": ("dry_run", True),
    "--no-dry-run": ("dry_run", False),
}

app = App(
    name="ghillie",
    help="Operator-facing CLI scaffold for the Ghillie MVP control plane.",
    version="0.1.0",
)
app.command(stack_app)
app.command(estate_app)
app.command(ingest_app)
app.command(export_app)
app.command(report_app)
app.command(metrics_app)


def parse_global_options(  # noqa: C901, PLR0912, PLR0915
    argv: list[str],
) -> tuple[GlobalOptions, list[str]]:
    """Parse root-global options before handing off to the noun command tree."""
    api_base_url: str | None = None
    auth_token: str | None = None
    output: typ.Literal["table", "json", "yaml"] | None = None
    log_level: typ.Literal["debug", "info", "warn", "error"] | None = None
    request_timeout_s: float | None = None
    non_interactive: bool | None = None
    dry_run: bool | None = None
    remaining: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in _OPTION_REQUIRES_VALUE:
            field_name = _OPTION_REQUIRES_VALUE[token]
            next_index = index + 1
            if next_index >= len(argv):
                msg = f"{token} requires a value"
                raise ValueError(msg)
            value = _coerce_root_value(field_name, argv[next_index])
            if field_name == "api_base_url":
                api_base_url = typ.cast("str", value)
            elif field_name == "auth_token":
                auth_token = typ.cast("str", value)
            elif field_name == "output":
                output = typ.cast('typ.Literal["table", "json", "yaml"]', value)
            elif field_name == "log_level":
                log_level = typ.cast(
                    'typ.Literal["debug", "info", "warn", "error"]', value
                )
            else:
                request_timeout_s = typ.cast("float", value)
            index += 2
            continue
        if option_with_value := _split_option_with_value(token):
            option_name, option_value = option_with_value
            field_name = _OPTION_REQUIRES_VALUE.get(option_name)
            if field_name is None:
                remaining = argv[index:]
                break
            value = _coerce_root_value(field_name, option_value)
            if field_name == "api_base_url":
                api_base_url = typ.cast("str", value)
            elif field_name == "auth_token":
                auth_token = typ.cast("str", value)
            elif field_name == "output":
                output = typ.cast('typ.Literal["table", "json", "yaml"]', value)
            elif field_name == "log_level":
                log_level = typ.cast(
                    'typ.Literal["debug", "info", "warn", "error"]', value
                )
            else:
                request_timeout_s = typ.cast("float", value)
            index += 1
            continue
        if token in _BOOLEAN_OPTION_VALUES:
            field_name, field_value = _BOOLEAN_OPTION_VALUES[token]
            if field_name == "non_interactive":
                non_interactive = field_value
            else:
                dry_run = field_value
            index += 1
            continue
        remaining = argv[index:]
        break
    else:
        remaining = []

    return (
        GlobalOptions(
            api_base_url=api_base_url,
            auth_token=auth_token,
            output=output,
            log_level=log_level,
            request_timeout_s=request_timeout_s,
            non_interactive=non_interactive,
            dry_run=dry_run,
        ),
        remaining,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the packaged CLI."""
    tokens = list(sys.argv[1:] if argv is None else argv)
    try:
        global_options, remaining = parse_global_options(tokens)
        config = resolve_cli_config(global_options, env=os.environ)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        with use_context(CommandContext(config=config)):
            result = app(
                remaining or ["--help"],
                exit_on_error=False,
                print_error=False,
            )
    except CycloptsError as exc:
        print(f"Error: {_format_cyclopts_error(exc)}", file=sys.stderr)
        return 2
    return _coerce_result_to_exit_code(result)


def _split_option_with_value(token: str) -> tuple[str, str] | None:
    if "=" not in token:
        return None
    option_name, option_value = token.split("=", 1)
    return option_name, option_value


def _coerce_root_value(field_name: str, raw_value: str) -> object:
    if field_name == "request_timeout_s":
        try:
            return float(raw_value)
        except ValueError as exc:
            msg = "--request-timeout-s must be a float"
            raise ValueError(msg) from exc
    return raw_value


def _coerce_result_to_exit_code(result: object) -> int:
    if result is None:
        return 0
    if isinstance(result, int):
        return result
    if isinstance(result, str):
        print(result)
        return 0
    return 0


def _format_cyclopts_error(error: CycloptsError) -> str:
    message = str(error)
    if "--backend" in message and "Literal" in message and "python-api" in message:
        invalid_value = message.split('"')[1]
        return f'invalid choice for --backend: "{invalid_value}"'
    return message
