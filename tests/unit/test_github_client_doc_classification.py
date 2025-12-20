"""Unit tests for documentation path classification helpers."""

from __future__ import annotations

import pytest

from ghillie.github.client import _classify_documentation_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/roadmap.md", (True, False)),
        (r"docs\\roadmap.md", (True, False)),
        ("docs/adr/001-design.md", (False, True)),
        (r"docs\\ADR\\001-design.md", (False, True)),
        ("docs/adr/roadmap.md", (True, True)),
        ("docs/architecture-decision/0001.md", (False, True)),
        (r"docs\\architecture-decision\\0002.md", (False, True)),
        ("docs/adr.v2/001.md", (False, True)),
        ("docs/adr", (False, True)),
        ("docs/adr.md", (False, False)),
        ("docs/architecture-decision.md", (False, False)),
        ("/docs/adr/001.md", (False, True)),
        (r"C:\\docs\\adr\\001.md", (False, True)),
    ],
)
def test_classify_documentation_path(path: str, expected: tuple[bool, bool]) -> None:
    """Path classification handles both POSIX and Windows separators."""
    assert _classify_documentation_path(path) == expected
