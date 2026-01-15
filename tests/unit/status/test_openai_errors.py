"""Unit tests for OpenAI status model error classes."""

from __future__ import annotations

from ghillie.status.errors import (
    OpenAIAPIError,
    OpenAIConfigError,
    OpenAIResponseShapeError,
)


class TestOpenAIAPIError:
    """Tests for OpenAI API error factory methods."""

    def test_http_error_factory(self) -> None:
        """http_error creates error with status code."""
        error = OpenAIAPIError.http_error(500)
        assert error.status_code == 500
        assert "500" in str(error)

    def test_http_error_factory_includes_context(self) -> None:
        """http_error message includes HTTP context."""
        error = OpenAIAPIError.http_error(503)
        assert "HTTP" in str(error) or "http" in str(error).lower()

    def test_rate_limited_factory(self) -> None:
        """rate_limited creates error for 429 responses."""
        error = OpenAIAPIError.rate_limited()
        assert error.status_code == 429
        assert "rate" in str(error).lower()

    def test_rate_limited_factory_with_retry_after(self) -> None:
        """rate_limited includes retry-after when provided."""
        error = OpenAIAPIError.rate_limited(retry_after=60)
        assert "60" in str(error)

    def test_timeout_factory(self) -> None:
        """Timeout factory creates error for request timeouts."""
        error = OpenAIAPIError.timeout()
        assert "timed out" in str(error).lower()


class TestOpenAIResponseShapeError:
    """Tests for response shape error factory methods."""

    def test_missing_factory(self) -> None:
        """Missing factory creates error for missing field."""
        error = OpenAIResponseShapeError.missing("choices[0].message")
        assert "choices[0].message" in str(error)

    def test_invalid_json_factory(self) -> None:
        """invalid_json creates error with content preview."""
        content = "not valid json at all"
        error = OpenAIResponseShapeError.invalid_json(content)
        assert "not valid json" in str(error)

    def test_invalid_json_factory_truncates_long_content(self) -> None:
        """invalid_json truncates very long content in error message."""
        long_content = "x" * 500
        error = OpenAIResponseShapeError.invalid_json(long_content)
        # Should truncate to reasonable length
        assert len(str(error)) < 300


class TestOpenAIConfigError:
    """Tests for configuration error factory methods."""

    def test_missing_api_key_factory(self) -> None:
        """missing_api_key creates error mentioning env var."""
        error = OpenAIConfigError.missing_api_key()
        assert "GHILLIE_OPENAI_API_KEY" in str(error)

    def test_empty_api_key_factory(self) -> None:
        """empty_api_key creates error about empty key."""
        error = OpenAIConfigError.empty_api_key()
        assert "empty" in str(error).lower() or "non-empty" in str(error).lower()
