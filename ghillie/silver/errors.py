"""Shared Silver-layer error types."""

from __future__ import annotations


class RawEventTransformError(Exception):
    """Raised when a raw event cannot be transformed deterministically."""

    def __init__(self, message: str, reason: str | None = None) -> None:
        """Store a machine-readable reason for programmatic handling."""
        super().__init__(message)
        self.reason = reason

    @classmethod
    def payload_mismatch(cls) -> RawEventTransformError:
        """Create a payload drift error."""
        return cls(
            "existing event fact payload no longer matches Bronze",
            reason="payload_mismatch",
        )

    @classmethod
    def concurrent_insert(cls) -> RawEventTransformError:
        """Create an error for concurrent inserts."""
        return cls(
            "failed to insert event fact; concurrent transform?",
            reason="concurrent_insert",
        )

    @classmethod
    def invalid_payload(cls, message: str) -> RawEventTransformError:
        """Create an error when payload cannot be decoded or validated."""
        return cls(message, reason="invalid_payload")

    @classmethod
    def repository_mismatch(cls) -> RawEventTransformError:
        """Create an error when a payload points to conflicting repositories."""
        return cls(
            "payload repository does not match existing record",
            reason="repository_mismatch",
        )

    @classmethod
    def entity_transform_failed(cls, exc: Exception) -> RawEventTransformError:
        """Create an error when an entity transformer raises unexpectedly."""
        return cls(f"entity transform failed: {exc}", reason="entity_transform_failed")

    @classmethod
    def datetime_requires_timezone(cls, field: str) -> RawEventTransformError:
        """Ensure datetime payloads remain timezone aware."""
        return cls.invalid_payload(f"{field} must be timezone aware")

    @classmethod
    def invalid_datetime_format(cls, field: str) -> RawEventTransformError:
        """Signal invalid ISO-8601 datetime payloads."""
        return cls.invalid_payload(f"{field} is not a valid ISO-8601 datetime")

    @classmethod
    def missing_datetime_timezone(cls, field: str) -> RawEventTransformError:
        """Signal missing timezone offsets on datetime payloads."""
        return cls.invalid_payload(f"{field} must include timezone information")

    @classmethod
    def unsupported_datetime_type(cls, field: str) -> RawEventTransformError:
        """Signal unsupported datetime payload shapes."""
        return cls.invalid_payload(
            f"{field} must be an ISO datetime string or datetime instance"
        )
