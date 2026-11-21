"""Per-invocation context for the packaged operator CLI."""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import typing as typ

from ghillie.cli.control_plane import ControlPlaneClient

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from .config import ResolvedCliConfig

    ClientFactory = cabc.Callable[[ResolvedCliConfig], ControlPlaneClient]

_CURRENT_CONTEXT: contextvars.ContextVar[CommandContext | None] = (
    contextvars.ContextVar("ghillie_cli_context", default=None)
)


@dataclasses.dataclass(frozen=True, slots=True)
class CommandContext:
    """Shared resolved state for one CLI invocation.

    ``client_factory`` is the substitution point for the control-plane client.
    Production leaves the default; tests pass a factory that returns a client
    with a mock transport, so the command boundary is replaced rather than the
    ``httpx`` module the client happens to use.
    """

    config: ResolvedCliConfig
    client_factory: ClientFactory = ControlPlaneClient


def get_current_context() -> CommandContext:
    """Return the current command context or fail if none is active."""
    context = _CURRENT_CONTEXT.get()
    if context is None:
        msg = "CLI command context has not been initialized"
        raise RuntimeError(msg)
    return context


@contextlib.contextmanager
def use_context(
    context: CommandContext,
) -> cabc.Generator[CommandContext]:
    """Temporarily set the current command context."""
    token = _CURRENT_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CURRENT_CONTEXT.reset(token)
