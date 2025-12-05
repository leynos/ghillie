"""Shared test utilities."""

from __future__ import annotations

import asyncio
import typing as typ


def run_async[T](coro_func: typ.Callable[[], typ.Coroutine[typ.Any, typ.Any, T]]) -> T:
    """Execute an async callable within the test context."""
    return asyncio.run(coro_func())
