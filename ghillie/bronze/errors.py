"""Shared Bronze-layer error types."""

from __future__ import annotations


class TimezoneAwareRequiredError(ValueError):
    """Raised when datetime inputs lack timezone information."""

    def __init__(self, context: str) -> None:
        """Attach a consistent message for the failing context."""
        super().__init__(f"{context} must be timezone aware")

    @classmethod
    def for_payload(cls) -> TimezoneAwareRequiredError:
        """Return an error indicating payload timestamps were naive."""
        return cls("payload datetime values")

    @classmethod
    def for_occurrence(cls) -> TimezoneAwareRequiredError:
        """Return an error indicating occurred_at was naive."""
        return cls("occurred_at")


class UnsupportedPayloadTypeError(ValueError):
    """Raised when payload contains non JSON-serialisable types."""

    def __init__(self, type_name: str) -> None:
        """Record the offending type name for diagnostics."""
        super().__init__(f"payload contains unsupported type {type_name}")
