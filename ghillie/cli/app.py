"""Root app and entry-point helpers for the packaged operator CLI."""

from __future__ import annotations

import os
import sys

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


def _consume_value_option(
    token: str, argv: list[str], index: int, state: dict[str, object]
) -> int:
    """Handle a ``--flag VALUE`` pair.

    Returns the advanced index (``index + 2``) if matched, or *index* if the
    token is not a recognised value-bearing option.
    Raises ``ValueError`` when the flag appears at the end of *argv*.
    """
    if token not in _OPTION_REQUIRES_VALUE:
        return index
    field_name = _OPTION_REQUIRES_VALUE[token]
    next_index = index + 1
    if next_index >= len(argv):
        msg = f"{token} requires a value"
        raise ValueError(msg)
    _apply_valued_option(field_name, argv[next_index], state)
    return index + 2


def _consume_inline_option(token: str, state: dict[str, object]) -> bool:
    """Handle a ``--flag=VALUE`` token.

    Returns ``True`` if the token was consumed, ``False`` otherwise —
    including when the flag name is not in ``_OPTION_REQUIRES_VALUE``.
    """
    parsed = _split_option_with_value(token)
    if parsed is None:
        return False
    option_name, option_value = parsed
    field_name = _OPTION_REQUIRES_VALUE.get(option_name)
    if field_name is None:
        return False
    _apply_valued_option(field_name, option_value, state)
    return True


def parse_global_options(
    argv: list[str],
) -> tuple[GlobalOptions, list[str]]:
    """Parse root-global options before handing off to the noun command tree."""
    state: dict[str, object] = {
        "api_base_url": None,
        "auth_token": None,
        "output": None,
        "log_level": None,
        "request_timeout_s": None,
        "non_interactive": None,
        "dry_run": None,
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        new_index = _consume_value_option(token, argv, index, state)
        if new_index != index:
            index = new_index
            continue
        if _consume_inline_option(token, state):
            index += 1
            continue
        if token in _BOOLEAN_OPTION_VALUES:
            field_name, field_value = _BOOLEAN_OPTION_VALUES[token]
            state[field_name] = field_value
            index += 1
            continue
        return GlobalOptions(**state), argv[index:]  # type: ignore[arg-type]  # safe: state values are validated/normalized to match GlobalOptions fields, argv[index:] is List[str]

    return GlobalOptions(**state), []  # type: ignore[arg-type]  # safe: state values are validated/normalized to match GlobalOptions fields


def main(argv: list[str] | None = None) -> int:
    """Run the packaged CLI."""
    tokens = list(sys.argv[1:] if argv is None else argv)
    try:
        global_options, remaining = parse_global_options(tokens)
        config = resolve_cli_config(global_options, env=os.environ)
    except (ValueError, TypeError) as exc:
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


def _apply_valued_option(
    field_name: str, raw_value: str, state: dict[str, object]
) -> None:
    """Coerce *raw_value* and store it in the accumulator *state*."""
    state[field_name] = _coerce_root_value(field_name, raw_value)


def _coerce_result_to_exit_code(result: object) -> int:
    if result is None:
        return 0
    if isinstance(result, int):
        return result
    if isinstance(result, str):
        print(result)
        return 0
    print(f"Unexpected command result: {result!r}", file=sys.stderr)
    return 1


def _is_invalid_backend_choice(message: str) -> bool:
    """Return True when the cyclopts error describes an invalid --backend value."""
    return "--backend" in message and (
        ("Literal" in message and "python-api" in message)
        or "RuntimeBackend" in message
    )


def _format_cyclopts_error(error: CycloptsError) -> str:
    message = str(error)
    if _is_invalid_backend_choice(message):
        parts = message.split('"')
        if len(parts) > 1:
            invalid_value = parts[1]
            return f'invalid choice for --backend: "{invalid_value}"'
    return message
