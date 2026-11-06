"""Errors specific to the repository registry."""

ESTATE_NOT_FOUND_REASON = "Estate not found"
"""Reason reported when a sync targets an estate that does not exist.

Callers translate a sync failure back into their own vocabulary by comparing
``RegistrySyncError.reason`` to this constant rather than to a repeated string
literal.
"""


class RegistryError(Exception):
    """Base class for registry errors."""


class RepositoryNotFoundError(RegistryError):
    """Raised when a repository cannot be found by slug."""

    def __init__(self, slug: str) -> None:
        """Initialise with the missing repository slug."""
        self.slug = slug
        msg = f"Repository not found: {slug}"
        super().__init__(msg)


class RegistrySyncError(RegistryError):
    """Raised when catalogue-to-Silver synchronisation fails."""

    def __init__(self, estate_key: str, reason: str) -> None:
        """Initialise with the estate key and failure reason."""
        self.estate_key = estate_key
        self.reason = reason
        msg = f"Sync failed for estate {estate_key}: {reason}"
        super().__init__(msg)
