"""Errors specific to the repository registry."""

from __future__ import annotations


class RegistryError(Exception):
    """Base class for registry errors."""


class RepositoryNotFoundError(RegistryError):
    """Raised when a repository cannot be found by slug."""

    def __init__(self, slug: str) -> None:
        """Initialise with the missing repository slug."""
        self.slug = slug
        super().__init__(f"Repository not found: {slug}")


class RegistrySyncError(RegistryError):
    """Raised when catalogue-to-Silver synchronisation fails."""

    def __init__(self, estate_key: str, reason: str) -> None:
        """Initialise with the estate key and failure reason."""
        self.estate_key = estate_key
        self.reason = reason
        super().__init__(f"Sync failed for estate {estate_key}: {reason}")
