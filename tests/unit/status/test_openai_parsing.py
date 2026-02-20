"""Unit tests for OpenAI response parsing."""

from __future__ import annotations

import contextlib
import typing as typ

import httpx
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

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from ghillie.evidence.models import RepositoryEvidenceBundle


@contextlib.asynccontextmanager
async def create_model_with_transport(
    config: OpenAIStatusModelConfig,
    transport: httpx.AsyncBaseTransport,
) -> cabc.AsyncIterator[OpenAIStatusModel]:
    """Create OpenAIStatusModel with custom transport, handling cleanup."""
    client = httpx.AsyncClient(transport=transport)
    model = OpenAIStatusModel(config, http_client=client)
    try:
        yield model
    finally:
        await model.aclose()
        await client.aclose()


class _RateLimitWithRetryTransport(httpx.AsyncBaseTransport):
    """Transport that returns 429 with Retry-After header."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Return rate limit response with retry-after."""
        return httpx.Response(
            status_code=429,
            headers={"Retry-After": "30"},
            json={"error": {"message": "Rate limit exceeded"}},
        )


class _RateLimitWithoutRetryTransport(httpx.AsyncBaseTransport):
    """Transport that returns 429 without Retry-After header."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Return rate limit response without retry-after."""
        return httpx.Response(
            status_code=429,
            json={"error": {"message": "Rate limit exceeded"}},
        )


class _BadGatewayTransport(httpx.AsyncBaseTransport):
    """Transport that returns 502 Bad Gateway."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Return bad gateway response."""
        return httpx.Response(
            status_code=502,
            json={"error": {"message": "Bad gateway"}},
        )


class _TimeoutTransport(httpx.AsyncBaseTransport):
    """Transport that raises TimeoutException."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Raise timeout exception."""
        raise httpx.TimeoutException("timeout", request=request)


class _NetworkErrorTransport(httpx.AsyncBaseTransport):
    """Transport that raises ConnectError."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Raise network connection error."""
        raise httpx.ConnectError("refused")


class _SuccessfulCompletionTransport(httpx.AsyncBaseTransport):
    """Transport that returns successful completion responses."""

    def __init__(
        self,
        *,
        usage_payloads: tuple[dict[str, object] | None, ...],
    ) -> None:
        self._usage_payloads = usage_payloads or (None,)
        self._index = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Return a valid chat completion response with optional usage."""
        usage = self._usage_payloads[min(self._index, len(self._usage_payloads) - 1)]
        self._index += 1

        body: dict[str, object] = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": '{"status": "on_track", "summary": "ok"}',
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        if usage is not None:
            body["usage"] = usage

        return httpx.Response(status_code=200, json=body)


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
    @pytest.mark.parametrize(
        ("transport_factory", "expected_status_code", "expected_message_fragment"),
        [
            (_RateLimitWithRetryTransport, 429, "30"),
            (_RateLimitWithoutRetryTransport, 429, "rate"),
            (_BadGatewayTransport, 502, "502"),
            (_TimeoutTransport, None, "timed out"),
            (_NetworkErrorTransport, None, "network"),
        ],
        ids=[
            "rate_limited_with_retry_after",
            "rate_limited_without_retry_after",
            "http_error_502",
            "timeout_error",
            "network_error",
        ],
    )
    async def test_error_handling(
        self,
        config: OpenAIStatusModelConfig,
        transport_factory: type[httpx.AsyncBaseTransport],
        expected_status_code: int | None,
        expected_message_fragment: str,
    ) -> None:
        """Verify HTTP error scenarios raise appropriate OpenAIAPIError."""
        transport = transport_factory()
        async with create_model_with_transport(config, transport) as model:
            with pytest.raises(OpenAIAPIError) as exc_info:
                await model._call_chat_completion("test prompt")

            if expected_status_code is not None:
                assert exc_info.value.status_code == expected_status_code

            assert expected_message_fragment in str(exc_info.value).lower()


class TestOpenAIInvocationMetrics:
    """Tests for model invocation metrics captured from API responses."""

    @pytest.fixture
    def config(self) -> OpenAIStatusModelConfig:
        """Create config for successful-call tests."""
        return OpenAIStatusModelConfig(
            api_key="test-key",
            endpoint="http://test.local/v1/chat/completions",
        )

    @pytest.mark.asyncio
    async def test_metrics_none_before_first_call(
        self,
        config: OpenAIStatusModelConfig,
    ) -> None:
        """No metrics are available before the first model invocation."""
        model = OpenAIStatusModel(config)
        try:
            assert model.last_invocation_metrics is None, (
                "Expected no invocation metrics before first model call"
            )
        finally:
            await model.aclose()

    @pytest.mark.asyncio
    async def test_extracts_token_usage_from_response(
        self,
        config: OpenAIStatusModelConfig,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Token usage is captured when the API returns a ``usage`` payload."""
        transport = _SuccessfulCompletionTransport(
            usage_payloads=(
                {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            )
        )
        async with create_model_with_transport(config, transport) as model:
            await model.summarize_repository(feature_evidence)

            metrics = model.last_invocation_metrics
            assert metrics is not None, (
                "Expected invocation metrics after successful model call"
            )
            assert metrics.prompt_tokens == 100, (
                "Expected prompt token count to match usage payload"
            )
            assert metrics.completion_tokens == 50, (
                "Expected completion token count to match usage payload"
            )
            assert metrics.total_tokens == 150, (
                "Expected total token count to match usage payload"
            )

    @pytest.mark.asyncio
    async def test_missing_usage_sets_empty_metrics(
        self,
        config: OpenAIStatusModelConfig,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Missing usage payload yields metrics with ``None`` token fields."""
        transport = _SuccessfulCompletionTransport(usage_payloads=(None,))
        async with create_model_with_transport(config, transport) as model:
            await model.summarize_repository(feature_evidence)

            metrics = model.last_invocation_metrics
            assert metrics is not None, (
                "Expected metrics object even when usage payload is absent"
            )
            assert metrics.prompt_tokens is None, (
                "Expected missing prompt token usage to remain None"
            )
            assert metrics.completion_tokens is None, (
                "Expected missing completion token usage to remain None"
            )
            assert metrics.total_tokens is None, (
                "Expected missing total token usage to remain None"
            )

    @pytest.mark.asyncio
    async def test_metrics_are_overwritten_per_call(
        self,
        config: OpenAIStatusModelConfig,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """A later invocation replaces token metrics from earlier calls."""
        transport = _SuccessfulCompletionTransport(
            usage_payloads=(
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
                {
                    "prompt_tokens": 20,
                    "completion_tokens": 8,
                    "total_tokens": 28,
                },
            )
        )
        async with create_model_with_transport(config, transport) as model:
            await model.summarize_repository(feature_evidence)
            await model.summarize_repository(feature_evidence)

            metrics = model.last_invocation_metrics
            assert metrics is not None, (
                "Expected invocation metrics after repeated model calls"
            )
            assert metrics.prompt_tokens == 20, (
                "Expected latest prompt token count to overwrite previous value"
            )
            assert metrics.completion_tokens == 8, (
                "Expected latest completion token count to overwrite previous value"
            )
            assert metrics.total_tokens == 28, (
                "Expected latest total token count to overwrite previous value"
            )

    @pytest.mark.asyncio
    async def test_non_integer_usage_values_are_ignored(
        self,
        config: OpenAIStatusModelConfig,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Non-integer usage values are coerced to ``None`` in metrics output."""
        transport = _SuccessfulCompletionTransport(
            usage_payloads=(
                {
                    "prompt_tokens": "100",
                    "completion_tokens": 50.0,
                    "total_tokens": "150.0",
                },
            )
        )
        async with create_model_with_transport(config, transport) as model:
            await model.summarize_repository(feature_evidence)

            metrics = model.last_invocation_metrics
            assert metrics is not None, (
                "Expected metrics object after successful completion response"
            )
            assert metrics.prompt_tokens is None, (
                "Expected non-integer prompt tokens to coerce to None"
            )
            assert metrics.completion_tokens is None, (
                "Expected non-integer completion tokens to coerce to None"
            )
            assert metrics.total_tokens is None, (
                "Expected non-integer total tokens to coerce to None"
            )
