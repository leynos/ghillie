"""Unit tests for OpenAI response parsing."""

from __future__ import annotations

import msgspec
import pytest

from ghillie.evidence.models import ReportStatus
from ghillie.status.config import OpenAIStatusModelConfig
from ghillie.status.errors import OpenAIAPIError, OpenAIResponseShapeError
from ghillie.status.openai_client import (
    LLMStatusResponse,
    OpenAIStatusModel,
    _parse_status,
)


class TestLLMStatusResponseParsing:
    """Tests for parsing LLM JSON responses."""

    def test_parse_valid_json_response(self) -> None:
        """Valid JSON with required fields parses successfully."""
        content = """{
            "status": "on_track",
            "summary": "Repository shows healthy development."
        }"""
        result = msgspec.json.decode(content, type=LLMStatusResponse)

        assert result.status == "on_track"
        assert result.summary == "Repository shows healthy development."
        assert result.highlights == []
        assert result.risks == []
        assert result.next_steps == []

    def test_parse_response_with_all_fields(self) -> None:
        """JSON with all fields parses correctly."""
        content = """{
            "status": "at_risk",
            "summary": "Elevated bug activity detected.",
            "highlights": ["Feature A shipped", "Tests improved"],
            "risks": ["Bug backlog growing"],
            "next_steps": ["Triage bugs", "Review PRs"]
        }"""
        result = msgspec.json.decode(content, type=LLMStatusResponse)

        assert result.status == "at_risk"
        assert result.summary == "Elevated bug activity detected."
        assert result.highlights == ["Feature A shipped", "Tests improved"]
        assert result.risks == ["Bug backlog growing"]
        assert result.next_steps == ["Triage bugs", "Review PRs"]

    def test_parse_response_with_minimal_fields(self) -> None:
        """JSON with only required fields parses with defaults."""
        content = '{"status": "unknown", "summary": "Minimal data."}'
        result = msgspec.json.decode(content, type=LLMStatusResponse)

        assert result.status == "unknown"
        assert result.summary == "Minimal data."
        assert result.highlights == []

    def test_parse_invalid_json_raises_error(self) -> None:
        """Invalid JSON raises DecodeError."""
        content = "not valid json {"
        with pytest.raises(msgspec.DecodeError):
            msgspec.json.decode(content, type=LLMStatusResponse)

    def test_parse_missing_status_raises_error(self) -> None:
        """JSON missing required 'status' field raises error."""
        content = '{"summary": "No status field"}'
        with pytest.raises(msgspec.DecodeError):
            msgspec.json.decode(content, type=LLMStatusResponse)

    def test_parse_missing_summary_raises_error(self) -> None:
        """JSON missing required 'summary' field raises error."""
        content = '{"status": "on_track"}'
        with pytest.raises(msgspec.DecodeError):
            msgspec.json.decode(content, type=LLMStatusResponse)


class TestStatusEnumParsing:
    """Tests for converting status strings to ReportStatus enum."""

    def test_parses_on_track(self) -> None:
        """'on_track' string parses to ON_TRACK enum."""
        assert _parse_status("on_track") == ReportStatus.ON_TRACK

    def test_parses_at_risk(self) -> None:
        """'at_risk' string parses to AT_RISK enum."""
        assert _parse_status("at_risk") == ReportStatus.AT_RISK

    def test_parses_blocked(self) -> None:
        """'blocked' string parses to BLOCKED enum."""
        assert _parse_status("blocked") == ReportStatus.BLOCKED

    def test_parses_unknown(self) -> None:
        """'unknown' string parses to UNKNOWN enum."""
        assert _parse_status("unknown") == ReportStatus.UNKNOWN

    def test_normalizes_hyphenated_status(self) -> None:
        """Status with hyphens normalizes to underscores."""
        assert _parse_status("on-track") == ReportStatus.ON_TRACK
        assert _parse_status("at-risk") == ReportStatus.AT_RISK

    def test_normalizes_case(self) -> None:
        """Status parsing is case-insensitive."""
        assert _parse_status("ON_TRACK") == ReportStatus.ON_TRACK
        assert _parse_status("At_Risk") == ReportStatus.AT_RISK

    def test_unknown_status_falls_back_to_unknown(self) -> None:
        """Unrecognized status values fall back to UNKNOWN."""
        assert _parse_status("invalid_status") == ReportStatus.UNKNOWN
        assert _parse_status("") == ReportStatus.UNKNOWN
        assert _parse_status("good") == ReportStatus.UNKNOWN


class TestOpenAIResponseExtraction:
    """Tests for extracting content from OpenAI API responses."""

    @pytest.fixture
    def model(self) -> OpenAIStatusModel:
        """Create model instance for testing internal methods."""
        config = OpenAIStatusModelConfig(api_key="test-key")
        return OpenAIStatusModel(config)

    def test_extract_content_from_valid_response(
        self, model: OpenAIStatusModel
    ) -> None:
        """Content extraction works for valid OpenAI response shape."""
        response_data = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": '{"status": "on_track", "summary": "Test"}',
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        content = model._extract_content(response_data)
        assert content == '{"status": "on_track", "summary": "Test"}'

    def test_extract_content_missing_choices(self, model: OpenAIStatusModel) -> None:
        """Missing 'choices' field raises OpenAIResponseShapeError."""
        response_data = {"id": "chatcmpl-123", "object": "chat.completion"}
        with pytest.raises(OpenAIResponseShapeError) as exc_info:
            model._extract_content(response_data)
        assert "choices" in str(exc_info.value)

    def test_extract_content_empty_choices(self, model: OpenAIStatusModel) -> None:
        """Empty 'choices' array raises OpenAIResponseShapeError."""
        response_data = {"choices": []}
        with pytest.raises(OpenAIResponseShapeError) as exc_info:
            model._extract_content(response_data)
        assert "choices" in str(exc_info.value)

    def test_extract_content_missing_message(self, model: OpenAIStatusModel) -> None:
        """Missing 'message' in choice raises OpenAIResponseShapeError."""
        response_data = {"choices": [{"index": 0, "finish_reason": "stop"}]}
        with pytest.raises(OpenAIResponseShapeError) as exc_info:
            model._extract_content(response_data)
        assert "message" in str(exc_info.value)

    def test_extract_content_missing_content(self, model: OpenAIStatusModel) -> None:
        """Missing 'content' in message raises OpenAIResponseShapeError."""
        response_data = {"choices": [{"index": 0, "message": {"role": "assistant"}}]}
        with pytest.raises(OpenAIResponseShapeError) as exc_info:
            model._extract_content(response_data)
        assert "content" in str(exc_info.value)


class TestOpenAIHTTPErrorHandling:
    """Tests for HTTP error handling in _call_chat_completion."""

    @pytest.fixture
    def config(self) -> OpenAIStatusModelConfig:
        """Create config for testing."""
        return OpenAIStatusModelConfig(
            api_key="test-key", endpoint="http://test.local/v1/chat/completions"
        )

    @pytest.mark.asyncio
    async def test_rate_limited_with_retry_after(
        self, config: OpenAIStatusModelConfig
    ) -> None:
        """429 with numeric Retry-After produces rate-limited OpenAIAPIError."""
        import httpx

        class RateLimitTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(
                self, request: httpx.Request
            ) -> httpx.Response:
                return httpx.Response(
                    status_code=429,
                    headers={"Retry-After": "30"},
                    json={"error": {"message": "Rate limit exceeded"}},
                )

        client = httpx.AsyncClient(transport=RateLimitTransport())
        model = OpenAIStatusModel(config, http_client=client)
        try:
            with pytest.raises(OpenAIAPIError) as exc_info:
                await model._call_chat_completion("test prompt")
            assert exc_info.value.status_code == 429
            assert "30" in str(exc_info.value)
        finally:
            await model.aclose()
            await client.aclose()

    @pytest.mark.asyncio
    async def test_rate_limited_without_retry_after(
        self, config: OpenAIStatusModelConfig
    ) -> None:
        """429 without Retry-After still produces rate-limited OpenAIAPIError."""
        import httpx

        class RateLimitTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(
                self, request: httpx.Request
            ) -> httpx.Response:
                return httpx.Response(
                    status_code=429,
                    json={"error": {"message": "Rate limit exceeded"}},
                )

        client = httpx.AsyncClient(transport=RateLimitTransport())
        model = OpenAIStatusModel(config, http_client=client)
        try:
            with pytest.raises(OpenAIAPIError) as exc_info:
                await model._call_chat_completion("test prompt")
            assert exc_info.value.status_code == 429
            assert "rate" in str(exc_info.value).lower()
        finally:
            await model.aclose()
            await client.aclose()

    @pytest.mark.asyncio
    async def test_http_error_502(self, config: OpenAIStatusModelConfig) -> None:
        """Non-2xx (e.g. 502) produces HTTP error OpenAIAPIError."""
        import httpx

        class BadGatewayTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(
                self, request: httpx.Request
            ) -> httpx.Response:
                return httpx.Response(
                    status_code=502,
                    json={"error": {"message": "Bad gateway"}},
                )

        client = httpx.AsyncClient(transport=BadGatewayTransport())
        model = OpenAIStatusModel(config, http_client=client)
        try:
            with pytest.raises(OpenAIAPIError) as exc_info:
                await model._call_chat_completion("test prompt")
            assert exc_info.value.status_code == 502
            assert "502" in str(exc_info.value)
        finally:
            await model.aclose()
            await client.aclose()

    @pytest.mark.asyncio
    async def test_timeout_error(self, config: OpenAIStatusModelConfig) -> None:
        """Timeout raises OpenAIAPIError with timeout message."""
        import httpx

        class TimeoutTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(
                self, request: httpx.Request
            ) -> httpx.Response:
                raise httpx.TimeoutException("timeout", request=request)

        client = httpx.AsyncClient(transport=TimeoutTransport())
        model = OpenAIStatusModel(config, http_client=client)
        try:
            with pytest.raises(OpenAIAPIError) as exc_info:
                await model._call_chat_completion("test prompt")
            assert "timed out" in str(exc_info.value).lower()
        finally:
            await model.aclose()
            await client.aclose()

    @pytest.mark.asyncio
    async def test_network_error(self, config: OpenAIStatusModelConfig) -> None:
        """Network errors (DNS, connection) raise OpenAIAPIError."""
        import httpx

        class NetworkErrorTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(
                self, request: httpx.Request
            ) -> httpx.Response:
                raise httpx.ConnectError("refused")

        client = httpx.AsyncClient(transport=NetworkErrorTransport())
        model = OpenAIStatusModel(config, http_client=client)
        try:
            with pytest.raises(OpenAIAPIError) as exc_info:
                await model._call_chat_completion("test prompt")
            assert "network" in str(exc_info.value).lower()
        finally:
            await model.aclose()
            await client.aclose()
