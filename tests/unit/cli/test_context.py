"""Unit tests for CLI context helpers."""

from __future__ import annotations

from contextlib import ExitStack

import pytest

from ghillie.cli.context import CommandContext, get_current_context, use_context


def test_get_current_context_without_active_context_raises() -> None:
    """get_current_context() should raise when no context has been set."""
    # Ensure there's no active context by not using use_context()
    with pytest.raises(RuntimeError, match="CLI command context"):
        get_current_context()


def test_use_context_sets_and_restores_context() -> None:
    """use_context should set and restore context inside and after its block."""
    from ghillie.cli.config import ResolvedCliConfig

    base_ctx = CommandContext(
        config=ResolvedCliConfig(
            api_base_url="http://127.0.0.1:8080",
            api_base_url_source="fallback",
            auth_token=None,
            output="table",
            log_level="info",
            request_timeout_s=30.0,
            non_interactive=True,
            dry_run=False,
        )
    )
    nested_ctx = CommandContext(
        config=ResolvedCliConfig(
            api_base_url="http://127.0.0.1:9999",
            api_base_url_source="flag",
            auth_token="token",  # noqa: S106
            output="json",
            log_level="debug",
            request_timeout_s=10.0,
            non_interactive=False,
            dry_run=True,
        )
    )

    # Establish an initial context
    with use_context(base_ctx):
        assert get_current_context() is base_ctx

        # Replace with a nested context
        with use_context(nested_ctx):
            assert get_current_context() is nested_ctx

        # After exiting nested context, original context is restored
        assert get_current_context() is base_ctx

    # After exiting outer context, there should be no active context
    with pytest.raises(RuntimeError):
        get_current_context()


def test_use_context_restores_context_on_exception() -> None:
    """use_context must restore the previous context even when the body raises."""
    from ghillie.cli.config import ResolvedCliConfig

    outer_ctx = CommandContext(
        config=ResolvedCliConfig(
            api_base_url="http://127.0.0.1:8080",
            api_base_url_source="fallback",
            auth_token=None,
            output="table",
            log_level="info",
            request_timeout_s=30.0,
            non_interactive=True,
            dry_run=False,
        )
    )
    inner_ctx = CommandContext(
        config=ResolvedCliConfig(
            api_base_url="http://127.0.0.1:9999",
            api_base_url_source="flag",
            auth_token=None,
            output="json",
            log_level="debug",
            request_timeout_s=10.0,
            non_interactive=False,
            dry_run=True,
        )
    )

    with use_context(outer_ctx):
        assert get_current_context() is outer_ctx

        def _raise_in_inner_context() -> None:
            with use_context(inner_ctx):
                assert get_current_context() is inner_ctx
                raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            _raise_in_inner_context()

        # The exception from the inner block must not corrupt the outer context
        assert get_current_context() is outer_ctx

    # No active context after exiting outer block
    with pytest.raises(RuntimeError):
        get_current_context()


def test_use_context_is_reentrant_and_nestable() -> None:
    """Multiple nested use_context invocations should unwind in LIFO order."""
    from ghillie.cli.config import ResolvedCliConfig

    ctx1 = CommandContext(
        config=ResolvedCliConfig(
            api_base_url="http://127.0.0.1:8081",
            api_base_url_source="fallback",
            auth_token=None,
            output="table",
            log_level="info",
            request_timeout_s=30.0,
            non_interactive=True,
            dry_run=False,
        )
    )
    ctx2 = CommandContext(
        config=ResolvedCliConfig(
            api_base_url="http://127.0.0.1:8082",
            api_base_url_source="fallback",
            auth_token=None,
            output="table",
            log_level="info",
            request_timeout_s=30.0,
            non_interactive=True,
            dry_run=False,
        )
    )
    ctx3 = CommandContext(
        config=ResolvedCliConfig(
            api_base_url="http://127.0.0.1:8083",
            api_base_url_source="fallback",
            auth_token=None,
            output="table",
            log_level="info",
            request_timeout_s=30.0,
            non_interactive=True,
            dry_run=False,
        )
    )

    with ExitStack() as stack:
        stack.enter_context(use_context(ctx1))
        assert get_current_context() is ctx1

        stack.enter_context(use_context(ctx2))
        assert get_current_context() is ctx2

        stack.enter_context(use_context(ctx3))
        assert get_current_context() is ctx3

    # After all are closed, there should be no active context
    with pytest.raises(RuntimeError):
        get_current_context()
