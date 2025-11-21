"""Fallback Python implementations.

This module provides Python fallbacks used when the optional Rust extension is
unavailable. Importing `hello` yields a simple greeting string as a sanity
check entry point.

Examples
--------
>>> from ghillie.pure import hello
>>> hello()
'hello from Python'

"""

from __future__ import annotations


def hello() -> str:
    """Return a friendly greeting from Python."""
    return "hello from Python"
