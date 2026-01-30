"""Custom exceptions for OpenAI status model operations."""

from __future__ import annotations

import typing as typ

from ghillie.status.constants import MAX_TEMPERATURE, MIN_TEMPERATURE

if typ.TYPE_CHECKING:
    import collections.abc as cabc

# Content preview length for error messages
_CONTENT_PREVIEW_LIMIT = 100


class OpenAIStatusError(Exception):
    """Base exception for all OpenAI status model errors.

    This provides a single catch point for all OpenAI-related errors
    in the status module.
    """


class OpenAIAPIError(OpenAIStatusError):
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
        msg = f"OpenAI API HTTP error {status_code}"
        return cls(msg, status_code=status_code)

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
        msg = f"OpenAI API network error: {detail}"
        return cls(msg)


class OpenAIResponseShapeError(OpenAIStatusError):
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
        msg = f"OpenAI response missing expected field: {field}"
        return cls(msg)

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
        msg = f"Failed to parse JSON from response: {preview}"
        return cls(msg)


class OpenAIConfigError(OpenAIStatusError):
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


class StatusModelConfigError(Exception):
    """Raised when status model factory configuration is invalid.

    This exception indicates issues with the environment configuration
    for selecting and configuring status model backends.

    """

    @classmethod
    def missing_backend(cls) -> StatusModelConfigError:
        """Create error when GHILLIE_STATUS_MODEL_BACKEND is not set.

        Returns
        -------
        StatusModelConfigError
            Error indicating the backend environment variable is required.

        """
        return cls("GHILLIE_STATUS_MODEL_BACKEND environment variable is required")

    @classmethod
    def invalid_backend(
        cls, name: str, valid_backends: cabc.Iterable[str]
    ) -> StatusModelConfigError:
        """Create error for unrecognized backend name.

        Parameters
        ----------
        name
            The invalid backend name that was provided.
        valid_backends
            Iterable of valid backend names.

        Returns
        -------
        StatusModelConfigError
            Error listing valid backend options.

        """
        valid_backends_str = ", ".join(f"'{b}'" for b in sorted(valid_backends))
        message = (
            f"Invalid status model backend '{name}'. "
            f"Valid options are: {valid_backends_str}"
        )
        return cls(message)

    @classmethod
    def invalid_parameter(
        cls, parameter_name: str, value: str, constraint: str
    ) -> StatusModelConfigError:
        """Create error for an invalid configuration parameter value.

        Parameters
        ----------
        parameter_name
            The name of the parameter that failed validation.
        value
            The invalid value that was provided.
        constraint
            A description of the valid value requirements.

        Returns
        -------
        StatusModelConfigError
            Error with formatted message describing the invalid parameter.

        """
        message = f"Invalid {parameter_name} '{value}'. {constraint}"
        return cls(message)

    @classmethod
    def invalid_temperature(cls, value: str) -> StatusModelConfigError:
        """Create error for invalid temperature value."""
        return cls.invalid_parameter(
            "temperature",
            value,
            f"Must be a float between {MIN_TEMPERATURE} and {MAX_TEMPERATURE}",
        )

    @classmethod
    def invalid_max_tokens(cls, value: str) -> StatusModelConfigError:
        """Create error for invalid max_tokens value."""
        return cls.invalid_parameter("max_tokens", value, "Must be a positive integer")
