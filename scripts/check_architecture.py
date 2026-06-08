"""Run Hecate with the Cyclopts version supported by Ghillie.

The pinned Hecate commit constructs ``cyclopts.App`` with ``result_action``.
Ghillie's supported Cyclopts range does not accept that keyword, but Hecate's
checker and command implementation do not otherwise depend on it. This wrapper
keeps the dependency pin intact while preserving Ghillie's existing CLI
dependency range.
"""

import typing as typ
from contextlib import contextmanager

import cyclopts

_OriginalApp: typ.Any = cyclopts.App


def _compat_app(*args: typ.Any, **kwargs: typ.Any) -> cyclopts.App:  # noqa: ANN401
    """Ignore Hecate's unsupported Cyclopts keyword during app construction."""
    kwargs.pop("result_action", None)
    return _OriginalApp(*args, **kwargs)  # type: ignore[return-value]


@contextmanager
def _patched_cyclopts_app() -> typ.Iterator[None]:
    """Temporarily install the Hecate compatibility constructor."""
    original_app = cyclopts.App
    cyclopts.App = _compat_app  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
    try:
        yield
    finally:
        cyclopts.App = original_app


def main() -> int:
    """Run the Hecate CLI entry point with repository defaults."""
    with _patched_cyclopts_app():
        from hecate.cli import main as hecate_main

        return hecate_main(["check", "--show-ignored", "--fail-on-unmatched-ignore"])


if __name__ == "__main__":
    raise SystemExit(main())
