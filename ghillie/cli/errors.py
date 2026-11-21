"""Local CLI failures that must never reach the control plane."""

from __future__ import annotations


class LocalInputError(Exception):
    """A local validation or I/O failure, presented with exit code ``2``.

    Attributes
    ----------
    code:
        Stable machine-readable code, matching the hint table's keys.
    message:
        Human-readable description safe to print.

    """

    def __init__(self, code: str, message: str) -> None:
        """Capture one local failure without any transport state."""
        super().__init__(message)
        self.code = code
        self.message = message
