"""Behavioural coverage for the packaged operator CLI contract."""

from __future__ import annotations

import contextlib
import io
import shlex
import typing as typ

import pytest
from pytest_bdd import parsers, scenario, then, when

from ghillie.cli import main


class OperatorCliContext(typ.TypedDict, total=False):
    """Shared mutable scenario state for CLI behaviour tests."""

    exit_code: int
    stdout: str
    stderr: str


@scenario(
    "../operator_cli_contract.feature",
    "Root help lists the top-level nouns",
)
def test_root_help_lists_top_level_nouns() -> None:
    """Wrap the root-help scenario."""


@scenario(
    "../operator_cli_contract.feature",
    "Stack up help exposes backend and wait options",
)
def test_stack_up_help_exposes_backend_and_wait_options() -> None:
    """Wrap the stack help scenario."""


@scenario(
    "../operator_cli_contract.feature",
    "Root global options parse before the noun command",
)
def test_root_global_options_parse_before_the_noun_command() -> None:
    """Wrap the global-options scenario."""


@scenario(
    "../operator_cli_contract.feature",
    "Invalid stack backend fails fast",
)
def test_invalid_stack_backend_fails_fast() -> None:
    """Wrap the invalid-backend scenario."""


@pytest.fixture
def operator_cli_context() -> OperatorCliContext:
    """Create mutable scenario state for a CLI invocation."""
    return {}


@when(parsers.parse('I run the operator CLI with "{arguments}"'))
def when_run_operator_cli(
    operator_cli_context: OperatorCliContext, arguments: str
) -> None:
    """Invoke the operator CLI and capture its stdout and stderr streams."""
    argv = shlex.split(arguments)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        exit_code = main(argv)

    operator_cli_context["exit_code"] = exit_code
    operator_cli_context["stdout"] = stdout.getvalue()
    operator_cli_context["stderr"] = stderr.getvalue()


@then(parsers.parse("the operator CLI exits with code {expected:d}"))
def then_operator_cli_exit_code(
    operator_cli_context: OperatorCliContext, expected: int
) -> None:
    """Assert the CLI exit code for the current scenario."""
    assert operator_cli_context["exit_code"] == expected


@then(parsers.parse('the operator CLI output mentions "{expected}"'))
def then_operator_cli_output_mentions(
    operator_cli_context: OperatorCliContext, expected: str
) -> None:
    """Assert the CLI stdout stream contains the expected fragment."""
    assert expected in operator_cli_context["stdout"]


@then(parsers.parse('the operator CLI error mentions "{expected}"'))
def then_operator_cli_error_mentions(
    operator_cli_context: OperatorCliContext, expected: str
) -> None:
    """Assert the CLI stderr stream contains the expected fragment."""
    assert expected in operator_cli_context["stderr"]
