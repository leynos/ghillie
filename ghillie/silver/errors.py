"""Shared Silver-layer error types."""

from __future__ import annotations

import enum


class RawEventTransformReason(enum.StrEnum):
    """Machine-readable reasons for Silver transform failures."""

    PAYLOAD_MISMATCH = "payload_mismatch"
    CONCURRENT_INSERT = "concurrent_insert"
    INVALID_PAYLOAD = "invalid_payload"
    REPOSITORY_MISMATCH = "repository_mismatch"
    ENTITY_TRANSFORM_FAILED = "entity_transform_failed"
    OCCURRED_AT_REQUIRED = "occurred_at_required"


class RawEventTransformError(Exception):
    """Raised when a raw event cannot be transformed deterministically."""

    def __init__(
        self,
        message: str,
        reason: RawEventTransformReason | str | None = None,
    ) -> None:
        """Store a machine-readable reason for programmatic handling."""
        super().__init__(message)
        self.reason = reason

    @classmethod
    def payload_mismatch(cls) -> RawEventTransformError:
        """Create a payload drift error."""
        return cls(
            "existing event fact payload no longer matches Bronze",
            reason=RawEventTransformReason.PAYLOAD_MISMATCH,
        )

    @classmethod
    def concurrent_insert(cls) -> RawEventTransformError:
        """Create an error for concurrent inserts."""
        return cls(
            "failed to insert event fact; concurrent transform?",
            reason=RawEventTransformReason.CONCURRENT_INSERT,
        )

    @classmethod
    def invalid_payload(cls, message: str) -> RawEventTransformError:
        """Create an error when payload cannot be decoded or validated."""
        return cls(message, reason=RawEventTransformReason.INVALID_PAYLOAD)

    @classmethod
    def repository_mismatch(cls) -> RawEventTransformError:
        """Create an error when a payload points to conflicting repositories."""
        return cls(
            "payload repository does not match existing record",
            reason=RawEventTransformReason.REPOSITORY_MISMATCH,
        )

    @classmethod
    def entity_transform_failed(cls, exc: Exception) -> RawEventTransformError:
        """Create an error when an entity transformer raises unexpectedly."""
        return cls(
            f"entity transform failed: {exc}",
            reason=RawEventTransformReason.ENTITY_TRANSFORM_FAILED,
        )

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

    @classmethod
    def occurred_at_required(cls) -> RawEventTransformError:
        """Signal missing occurred_at for documentation changes."""
        return cls(
            "occurred_at is required for documentation changes",
            reason=RawEventTransformReason.OCCURRED_AT_REQUIRED,
        )
