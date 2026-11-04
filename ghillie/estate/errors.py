"""Error vocabulary for estate management.

The driving port owns its errors so HTTP and CLI adapters never import a
catalogue or registry exception. Each error carries the minimum data an adapter
needs to render the documented error contract.
"""

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class Issue:
    """One machine-readable validation problem.

    Attributes
    ----------
    code:
        Stable identifier for the kind of problem.
    message:
        Human-readable explanation.

    """

    code: str
    message: str


class EstateError(Exception):
    """Base class for estate-management failures."""


class EstateNotFoundError(EstateError):
    """Raised when an estate cannot be found by key.

    Attributes
    ----------
    estate_key:
        Key that did not resolve to an estate.

    """

    def __init__(self, estate_key: str) -> None:
        """Initialize with the missing estate key."""
        self.estate_key = estate_key
        super().__init__(f"Estate not found: {estate_key}")


class InvalidEstateKeyError(EstateError):
    """Raised when an estate key fails a creation or reference rule.

    Attributes
    ----------
    estate_key:
        Key that failed validation.
    reason:
        Human-readable description of the rule that was broken.

    """

    def __init__(self, estate_key: str, reason: str) -> None:
        """Initialize with the rejected key and the reason."""
        self.estate_key = estate_key
        self.reason = reason
        super().__init__(f"Invalid estate key {estate_key!r}: {reason}")


class InvalidPaginationError(EstateError):
    """Raised when a page limit or offset is outside its allowed range.

    Attributes
    ----------
    field:
        Name of the pagination field that failed validation.
    reason:
        Human-readable description of the allowed range.

    """

    def __init__(self, field: str, reason: str) -> None:
        """Initialize with the offending field and the reason."""
        self.field = field
        self.reason = reason
        super().__init__(f"Invalid {field}: {reason}")


class CatalogueRejectedError(EstateError):
    """Raised when uploaded catalogue text cannot be accepted.

    Attributes
    ----------
    issues:
        Every validation problem found in the uploaded document.

    """

    def __init__(self, issues: tuple[Issue, ...]) -> None:
        """Initialize with every validation issue found."""
        self.issues = issues
        messages = "; ".join(issue.message for issue in issues)
        super().__init__(f"Catalogue rejected: {messages}")


class RepositoryNotFoundError(EstateError):
    """Raised when a repository cannot be found by owner and name.

    Attributes
    ----------
    owner:
        GitHub repository owner that was queried.
    name:
        GitHub repository name that was queried.

    """

    def __init__(self, owner: str, name: str) -> None:
        """Initialize with the missing repository identity."""
        self.owner = owner
        self.name = name
        super().__init__(f"Repository not found: {owner}/{name}")


class EstateConflictError(EstateError):
    """Raised when a write violates a uniqueness constraint."""


class StorageUnavailableError(EstateError):
    """Raised when the database cannot be reached."""


class RegistrySyncFailedError(EstateError):
    """Raised when a registry sync fails for a reason other than storage."""
