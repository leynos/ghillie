"""Unit tests for OpenAI response parsing."""

from __future__ import annotations

import contextlib
import typing as typ
from http import HTTPStatus

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


class _ExpectedMetrics(typ.NamedTuple):
    """Expected token-count values for a parametrised metrics assertion."""

    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


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
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            headers={"Retry-After": "30"},
            json={"error": {"message": "Rate limit exceeded"}},
        )


class _RateLimitWithoutRetryTransport(httpx.AsyncBaseTransport):
    """Transport that returns 429 without Retry-After header."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Return rate limit response without retry-after."""
        return httpx.Response(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            json={"error": {"message": "Rate limit exceeded"}},
        )


class _BadGatewayTransport(httpx.AsyncBaseTransport):
    """Transport that returns 502 Bad Gateway."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Return bad gateway response."""
        return httpx.Response(
            status_code=HTTPStatus.BAD_GATEWAY,
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
        usage_payloads: tuple[object | None, ...],
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

        return httpx.Response(status_code=HTTPStatus.OK, json=body)


class _JSONBodyTransport(httpx.AsyncBaseTransport):
    """Transport that returns a caller-provided JSON response body."""

    def __init__(self, *, body: object) -> None:
        self._body = body

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Return the configured JSON payload as the response body."""
        return httpx.Response(status_code=HTTPStatus.OK, json=self._body)


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


class TestOpenAIResponseParsingViaPublicAPI:
    """Tests for response parsing through ``summarize_repository``."""

    @pytest.fixture
    def config(self) -> OpenAIStatusModelConfig:
        """Create config for response parsing tests."""
        return OpenAIStatusModelConfig(
            api_key="test-key",
            endpoint="http://test.local/v1/chat/completions",
        )

    @pytest.mark.asyncio
    async def test_summarize_repository_parses_valid_response(
        self,
        config: OpenAIStatusModelConfig,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """A valid response body produces the expected status result."""
        response_data: dict[str, object] = {
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
        transport = _JSONBodyTransport(body=response_data)
        async with create_model_with_transport(config, transport) as model:
            result = await model.summarize_repository(feature_evidence)

        assert result.status == ReportStatus.ON_TRACK
        assert result.summary == "Test"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("response_data", "expected_fragment"),
        [
            (
                {
                    "id": "chatcmpl-123",
                    "object": "chat.completion",
                },
                "choices",
            ),
            ({"choices": []}, "choices"),
            ({"choices": [{"index": 0, "finish_reason": "stop"}]}, "message"),
            (
                {"choices": [{"index": 0, "message": {"role": "assistant"}}]},
                "content",
            ),
            ({"choices": ["not-a-dict"]}, "choices[0]"),
            (
                {"choices": [{"message": {"role": "assistant", "content": ["bad"]}}]},
                "choices[0].message.content",
            ),
        ],
        ids=[
            "missing_choices",
            "empty_choices",
            "missing_message",
            "missing_content",
            "non_mapping_choice",
            "non_string_content",
        ],
    )
    async def test_summarize_repository_rejects_invalid_response_shapes(
        self,
        config: OpenAIStatusModelConfig,
        feature_evidence: RepositoryEvidenceBundle,
        response_data: dict[str, object],
        expected_fragment: str,
    ) -> None:
        """Malformed response bodies surface shape errors via the public API."""
        transport = _JSONBodyTransport(body=response_data)
        async with create_model_with_transport(config, transport) as model:
            with pytest.raises(OpenAIResponseShapeError) as exc_info:
                await model.summarize_repository(feature_evidence)

        assert expected_fragment in str(exc_info.value)


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
    @pytest.mark.parametrize(
        ("usage_payload", "expected_metrics"),
        [
            (
                {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                _ExpectedMetrics(100, 50, 150),
            ),
            (None, _ExpectedMetrics(None, None, None)),
            (
                {
                    "prompt_tokens": "100",
                    "completion_tokens": 50.0,
                    "total_tokens": "150.0",
                },
                _ExpectedMetrics(None, None, None),
            ),
            (["bad-usage"], _ExpectedMetrics(None, None, None)),
            ({1: 10, 2: 20, 3: 30}, _ExpectedMetrics(None, None, None)),
        ],
        ids=[
            "valid_integer_tokens",
            "missing_usage",
            "non_integer_usage_values",
            "non_mapping_usage",
            "non_string_key_dict",
        ],
    )
    async def test_usage_payload_produces_expected_metrics(
        self,
        config: OpenAIStatusModelConfig,
        feature_evidence: RepositoryEvidenceBundle,
        usage_payload: object,
        expected_metrics: _ExpectedMetrics,
    ) -> None:
        """Usage payloads map to the expected invocation metrics."""
        transport = _SuccessfulCompletionTransport(usage_payloads=(usage_payload,))
        async with create_model_with_transport(config, transport) as model:
            await model.summarize_repository(feature_evidence)

            metrics = model.last_invocation_metrics
            assert metrics is not None, (
                "Expected invocation metrics after successful model call"
            )
            assert metrics.prompt_tokens == expected_metrics.prompt_tokens, (
                f"Expected prompt_tokens to equal {expected_metrics.prompt_tokens!r} for "
                f"usage_payload={usage_payload!r}"
            )
            assert metrics.completion_tokens == expected_metrics.completion_tokens, (
                f"Expected completion_tokens to equal "
                f"{expected_metrics.completion_tokens!r} for "
                f"usage_payload={usage_payload!r}"
            )
            assert metrics.total_tokens == expected_metrics.total_tokens, (
                f"Expected total_tokens to equal {expected_metrics.total_tokens!r} for "
                f"usage_payload={usage_payload!r}"
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
    async def test_non_string_key_usage_dict_sets_empty_metrics(
        self,
        config: OpenAIStatusModelConfig,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Dict usage payloads with non-string keys leave invocation metrics empty."""
        transport = _SuccessfulCompletionTransport(
            usage_payloads=({1: 10, 2: 20, 3: 30},)
        )
        async with create_model_with_transport(config, transport) as model:
            await model.summarize_repository(feature_evidence)

            metrics = model.last_invocation_metrics
            assert metrics is not None, (
                "Expected metrics object after successful completion response"
            )
            assert metrics.prompt_tokens is None, (
                "Expected prompt token count to stay None for non-string usage keys"
            )
            assert metrics.completion_tokens is None, (
                "Expected completion token count to stay None for non-string usage keys"
            )
            assert metrics.total_tokens is None, (
                "Expected total token count to stay None for non-string usage keys"
            )
