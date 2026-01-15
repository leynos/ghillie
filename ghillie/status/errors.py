"""Custom exceptions for OpenAI status model operations."""

from __future__ import annotations

# Content preview length for error messages
_CONTENT_PREVIEW_LIMIT = 100


class OpenAIAPIError(RuntimeError):
    """Raised when OpenAI API returns an error response.

    Attributes
    ----------
    status_code
        HTTP status code from the API response, if available.

    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        """Initialise the error with message and optional status code.

        Parameters
        ----------
        message
            Human-readable error description.
        status_code
            HTTP status code from the API response.

        """
        self.status_code = status_code
        super().__init__(message)

    @classmethod
    def http_error(cls, status_code: int) -> OpenAIAPIError:
        """Create error for HTTP error responses.

        Parameters
        ----------
        status_code
            HTTP status code from the response.

        Returns
        -------
        OpenAIAPIError
            Error with status code context.

        """
        return cls(f"OpenAI API HTTP error {status_code}", status_code=status_code)

    @classmethod
    def rate_limited(cls, retry_after: int | None = None) -> OpenAIAPIError:
        """Create error for rate limit (429) responses.

        Parameters
        ----------
        retry_after
            Seconds to wait before retrying, from Retry-After header.

        Returns
        -------
        OpenAIAPIError
            Error indicating rate limiting.

        """
        msg = "OpenAI API rate limited"
        if retry_after is not None:
            msg = f"{msg}, retry after {retry_after}s"
        return cls(msg, status_code=429)

    @classmethod
    def timeout(cls) -> OpenAIAPIError:
        """Create error for request timeouts.

        Returns
        -------
        OpenAIAPIError
            Error indicating request timeout.

        """
        return cls("OpenAI API request timed out")

    @classmethod
    def network_error(cls, detail: str) -> OpenAIAPIError:
        """Create error for network failures (DNS, connection, TLS, etc.).

        Parameters
        ----------
        detail
            Description of the network failure.

        Returns
        -------
        OpenAIAPIError
            Error indicating network failure.

        """
        return cls(f"OpenAI API network error: {detail}")


class OpenAIResponseShapeError(RuntimeError):
    """Raised when OpenAI response is missing expected fields or malformed."""

    @classmethod
    def missing(cls, field: str) -> OpenAIResponseShapeError:
        """Create error for missing response field.

        Parameters
        ----------
        field
            Name or path of the missing field.

        Returns
        -------
        OpenAIResponseShapeError
            Error with field context.

        """
        return cls(f"OpenAI response missing expected field: {field}")

    @classmethod
    def invalid_json(cls, content: str) -> OpenAIResponseShapeError:
        """Create error for invalid JSON in response content.

        Parameters
        ----------
        content
            The content that failed to parse as JSON.

        Returns
        -------
        OpenAIResponseShapeError
            Error with truncated content preview.

        """
        if len(content) > _CONTENT_PREVIEW_LIMIT:
            preview = content[:_CONTENT_PREVIEW_LIMIT] + "..."
        else:
            preview = content
        return cls(f"Failed to parse JSON from response: {preview}")


class OpenAIConfigError(RuntimeError):
    """Raised when OpenAI client configuration is invalid."""

    @classmethod
    def missing_api_key(cls) -> OpenAIConfigError:
        """Create error for missing API key environment variable.

        Returns
        -------
        OpenAIConfigError
            Error indicating missing GHILLIE_OPENAI_API_KEY.

        """
        return cls("GHILLIE_OPENAI_API_KEY environment variable is required")

    @classmethod
    def empty_api_key(cls) -> OpenAIConfigError:
        """Create error for empty API key.

        Returns
        -------
        OpenAIConfigError
            Error indicating API key must be non-empty.

        """
        return cls("OpenAI API key must be non-empty")
