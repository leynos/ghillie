"""Unit tests for OpenAI status model configuration."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from ghillie.status.config import OpenAIStatusModelConfig
from ghillie.status.errors import OpenAIConfigError


class TestOpenAIStatusModelConfigFromEnv:
    """Tests for configuration loading from environment variables."""

    def test_from_env_requires_api_key(self) -> None:
        """Configuration fails when GHILLIE_OPENAI_API_KEY is missing."""
        env = {}
        with mock.patch.dict(os.environ, env, clear=True):
            with pytest.raises(OpenAIConfigError) as exc_info:
                OpenAIStatusModelConfig.from_env()
            assert "GHILLIE_OPENAI_API_KEY" in str(exc_info.value)

    def test_from_env_uses_defaults(self) -> None:
        """Configuration uses default values when only API key is provided."""
        env = {"GHILLIE_OPENAI_API_KEY": "test-key-123"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = OpenAIStatusModelConfig.from_env()

        assert config.api_key == "test-key-123"
        assert config.endpoint == "https://api.openai.com/v1/chat/completions"
        assert config.model == "gpt-5.1-thinking"
        assert config.timeout_s == 120.0
        assert config.temperature == 0.3
        assert config.max_tokens == 2048

    def test_from_env_reads_custom_endpoint(self) -> None:
        """Configuration reads custom endpoint from environment."""
        env = {
            "GHILLIE_OPENAI_API_KEY": "test-key",
            "GHILLIE_OPENAI_ENDPOINT": "http://localhost:8080/v1/chat/completions",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = OpenAIStatusModelConfig.from_env()

        assert config.endpoint == "http://localhost:8080/v1/chat/completions"

    def test_from_env_reads_custom_model(self) -> None:
        """Configuration reads custom model from environment."""
        env = {
            "GHILLIE_OPENAI_API_KEY": "test-key",
            "GHILLIE_OPENAI_MODEL": "gpt-4-turbo",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = OpenAIStatusModelConfig.from_env()

        assert config.model == "gpt-4-turbo"


class TestOpenAIStatusModelConfigValidation:
    """Tests for configuration validation."""

    @pytest.mark.parametrize(
        ("api_key", "description"),
        [
            ("", "empty string"),
            ("   ", "whitespace only"),
            ("\t\n", "whitespace with tab and newline"),
        ],
        ids=["empty", "spaces", "mixed-whitespace"],
    )
    def test_rejects_invalid_api_key(self, api_key: str, description: str) -> None:
        """Configuration fails when API key is invalid ({description})."""
        env = {"GHILLIE_OPENAI_API_KEY": api_key}
        with mock.patch.dict(os.environ, env, clear=True):
            with pytest.raises(OpenAIConfigError) as exc_info:
                OpenAIStatusModelConfig.from_env()
            assert "non-empty" in str(exc_info.value).lower()

    def test_config_is_frozen(self) -> None:
        """Configuration dataclass is frozen (immutable).

        Verifies that the dataclass is declared frozen and that
        attempting to mutate a field raises FrozenInstanceError.
        """
        import dataclasses

        config = OpenAIStatusModelConfig(api_key="test-key")

        # Verify frozen flag is set in dataclass metadata
        assert config.__dataclass_params__.frozen is True

        # Verify runtime mutation raises FrozenInstanceError.
        # Direct assignment is required to test frozen dataclass behaviour.
        # Note: object.__setattr__ bypasses frozen protection and does not
        # raise FrozenInstanceError, so we must use direct assignment here.
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.api_key = "new-key"  # type: ignore[misc]  # intentional
