"""Run Hecate with the Cyclopts version supported by Ghillie.

The pinned Hecate commit constructs ``cyclopts.App`` with ``result_action``.
Ghillie's supported Cyclopts range does not accept that keyword, but Hecate's
checker and command implementation do not otherwise depend on it. This wrapper
keeps the dependency pin intact while preserving Ghillie's existing CLI
dependency range.
"""

import typing as typ

import cyclopts

_OriginalApp: typ.Any = cyclopts.App


def _compat_app(*args: object, **kwargs: object) -> cyclopts.App:
    """Ignore Hecate's unsupported Cyclopts keyword during app construction."""
    kwargs.pop("result_action", None)
    return typ.cast(
        "cyclopts.App",
        _OriginalApp(*typ.cast("typ.Any", args), **typ.cast("typ.Any", kwargs)),
    )


def main() -> int:
    """Run the Hecate CLI entry point with repository defaults."""
    cyclopts.App = typ.cast("typ.Any", _compat_app)
    from hecate.cli import main as hecate_main

    return hecate_main(["check", "--show-ignored", "--fail-on-unmatched-ignore"])


if __name__ == "__main__":
    raise SystemExit(main())
