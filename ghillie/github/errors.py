"""GitHub ingestion errors."""

from __future__ import annotations


class GitHubAPIError(RuntimeError):
    """Raised when GitHub returns an error response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        """Initialise with a message and optional HTTP status code."""
        self.status_code = status_code
        super().__init__(message)

    @classmethod
    def http_error(cls, status_code: int) -> GitHubAPIError:
        """Return an error for non-2xx HTTP responses."""
        return cls(f"GitHub GraphQL HTTP {status_code}", status_code=status_code)

    @classmethod
    def graphql_errors(cls, errors: object) -> GitHubAPIError:
        """Return an error for GraphQL `errors` payloads."""
        return cls(f"GitHub GraphQL errors: {errors}")


class GitHubResponseShapeError(RuntimeError):
    """Raised when GitHub GraphQL responses are missing expected fields."""

    @classmethod
    def missing(cls, field: str) -> GitHubResponseShapeError:
        """Return an error for a missing GraphQL response field."""
        return cls(f"GitHub GraphQL response missing expected field: {field}")


class GitHubConfigError(RuntimeError):
    """Raised when GitHub client configuration is invalid."""

    @classmethod
    def missing_token(cls) -> GitHubConfigError:
        """Return an error when no GitHub token is configured."""
        return cls("GHILLIE_GITHUB_TOKEN is required for GitHub API")

    @classmethod
    def empty_token(cls) -> GitHubConfigError:
        """Return an error when the provided token is empty."""
        return cls("GitHub token must be non-empty")
