"""Unit tests for OpenAI response parsing."""

from __future__ import annotations

import pytest

from ghillie.evidence.models import ReportStatus
from ghillie.status.errors import OpenAIResponseShapeError
from ghillie.status.openai_client import (
    LLMStatusResponse,
    OpenAIStatusModel,
    _parse_status,
)


class TestLLMStatusResponseParsing:
    """Tests for parsing LLM JSON responses."""

    def test_parse_valid_json_response(self) -> None:
        """Valid JSON with required fields parses successfully."""
        import msgspec

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
        import msgspec

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
        import msgspec

        content = '{"status": "unknown", "summary": "Minimal data."}'
        result = msgspec.json.decode(content, type=LLMStatusResponse)

        assert result.status == "unknown"
        assert result.summary == "Minimal data."
        assert result.highlights == []

    def test_parse_invalid_json_raises_error(self) -> None:
        """Invalid JSON raises DecodeError."""
        import msgspec

        content = "not valid json {"
        with pytest.raises(msgspec.DecodeError):
            msgspec.json.decode(content, type=LLMStatusResponse)

    def test_parse_missing_status_raises_error(self) -> None:
        """JSON missing required 'status' field raises error."""
        import msgspec

        content = '{"summary": "No status field"}'
        with pytest.raises(msgspec.DecodeError):
            msgspec.json.decode(content, type=LLMStatusResponse)

    def test_parse_missing_summary_raises_error(self) -> None:
        """JSON missing required 'summary' field raises error."""
        import msgspec

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

    def test_extract_content_from_valid_response(self) -> None:
        """Content extraction works for valid OpenAI response shape."""
        # Create model instance for testing internal method
        from ghillie.status.config import OpenAIStatusModelConfig

        config = OpenAIStatusModelConfig(api_key="test-key")
        model = OpenAIStatusModel(config)

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

    def test_extract_content_missing_choices(self) -> None:
        """Missing 'choices' field raises OpenAIResponseShapeError."""
        from ghillie.status.config import OpenAIStatusModelConfig

        config = OpenAIStatusModelConfig(api_key="test-key")
        model = OpenAIStatusModel(config)

        response_data = {"id": "chatcmpl-123", "object": "chat.completion"}
        with pytest.raises(OpenAIResponseShapeError) as exc_info:
            model._extract_content(response_data)
        assert "choices" in str(exc_info.value)

    def test_extract_content_empty_choices(self) -> None:
        """Empty 'choices' array raises OpenAIResponseShapeError."""
        from ghillie.status.config import OpenAIStatusModelConfig

        config = OpenAIStatusModelConfig(api_key="test-key")
        model = OpenAIStatusModel(config)

        response_data = {"choices": []}
        with pytest.raises(OpenAIResponseShapeError) as exc_info:
            model._extract_content(response_data)
        assert "choices" in str(exc_info.value)

    def test_extract_content_missing_message(self) -> None:
        """Missing 'message' in choice raises OpenAIResponseShapeError."""
        from ghillie.status.config import OpenAIStatusModelConfig

        config = OpenAIStatusModelConfig(api_key="test-key")
        model = OpenAIStatusModel(config)

        response_data = {"choices": [{"index": 0, "finish_reason": "stop"}]}
        with pytest.raises(OpenAIResponseShapeError) as exc_info:
            model._extract_content(response_data)
        assert "message" in str(exc_info.value)

    def test_extract_content_missing_content(self) -> None:
        """Missing 'content' in message raises OpenAIResponseShapeError."""
        from ghillie.status.config import OpenAIStatusModelConfig

        config = OpenAIStatusModelConfig(api_key="test-key")
        model = OpenAIStatusModel(config)

        response_data = {"choices": [{"index": 0, "message": {"role": "assistant"}}]}
        with pytest.raises(OpenAIResponseShapeError) as exc_info:
            model._extract_content(response_data)
        assert "content" in str(exc_info.value)
