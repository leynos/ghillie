"""Unit tests for OpenAI status model configuration."""

from __future__ import annotations

import os
import typing as typ
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
            assert "GHILLIE_OPENAI_API_KEY" in str(exc_info.value), (
                "Error message should reference missing env var"
            )

    def test_from_env_uses_defaults(self) -> None:
        """Configuration uses default values when only API key is provided."""
        env = {"GHILLIE_OPENAI_API_KEY": "test-key-123"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = OpenAIStatusModelConfig.from_env()

        assert config.api_key == "test-key-123", "Expected API key from env"
        assert config.endpoint == "https://api.openai.com/v1/chat/completions", (
            "Expected default OpenAI endpoint"
        )
        assert config.model == "gpt-5.1-thinking", "Expected default model"
        assert config.timeout_s == 120.0, "Expected default timeout of 120s"
        assert config.temperature == 0.3, "Expected default temperature of 0.3"
        assert config.max_tokens == 2048, "Expected default max_tokens of 2048"

    @pytest.mark.parametrize(
        ("env_var", "attr_name", "value", "expected"),
        [
            (
                "GHILLIE_OPENAI_ENDPOINT",
                "endpoint",
                "http://localhost:8080/v1/chat/completions",
                "http://localhost:8080/v1/chat/completions",
            ),
            ("GHILLIE_OPENAI_MODEL", "model", "gpt-4-turbo", "gpt-4-turbo"),
        ],
        ids=["custom-endpoint", "custom-model"],
    )
    def test_from_env_reads_custom_values(
        self, env_var: str, attr_name: str, value: str, expected: str
    ) -> None:
        """Configuration reads custom values from environment."""
        env = {
            "GHILLIE_OPENAI_API_KEY": "test-key",
            env_var: value,
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = OpenAIStatusModelConfig.from_env()

        actual = getattr(config, attr_name)
        assert actual == expected, f"Expected custom {attr_name} from env"


class TestOpenAIStatusModelConfigValidation:
    """Tests for configuration validation."""

    @pytest.mark.parametrize(
        "api_key",
        [
            "",
            "   ",
            "\t\n",
        ],
        ids=["empty", "spaces", "mixed-whitespace"],
    )
    def test_rejects_invalid_api_key(self, api_key: str) -> None:
        """Configuration fails when API key is invalid."""
        env = {"GHILLIE_OPENAI_API_KEY": api_key}
        with mock.patch.dict(os.environ, env, clear=True):
            with pytest.raises(OpenAIConfigError) as exc_info:
                OpenAIStatusModelConfig.from_env()
            assert "non-empty" in str(exc_info.value).lower(), (
                "Error message should indicate API key must be non-empty"
            )

    def test_config_is_frozen(self) -> None:
        """Configuration dataclass is frozen (immutable).

        Verifies that the dataclass is declared frozen and that
        attempting to mutate a field raises FrozenInstanceError.
        """
        import dataclasses

        config = OpenAIStatusModelConfig(api_key="test-key")

        # Verify frozen flag is set in dataclass metadata
        assert config.__dataclass_params__.frozen is True, (
            "Dataclass should be declared frozen"
        )

        # Verify runtime mutation raises FrozenInstanceError.
        mutable_config = typ.cast("typ.Any", config)
        with pytest.raises(dataclasses.FrozenInstanceError):
            mutable_config.api_key = "new-key"


class TestOpenAIStatusModelConfigNumericParametersFromEnv:
    """Tests for numeric parameter configuration from environment."""

    @pytest.mark.parametrize(
        ("env_var", "attr_name", "param_value", "expected"),
        [
            ("GHILLIE_OPENAI_TEMPERATURE", "temperature", "0.7", 0.7),
            ("GHILLIE_OPENAI_TEMPERATURE", "temperature", "0.0", 0.0),
            ("GHILLIE_OPENAI_TEMPERATURE", "temperature", "2.0", 2.0),
            ("GHILLIE_OPENAI_MAX_TOKENS", "max_tokens", "4096", 4096),
            ("GHILLIE_OPENAI_MAX_TOKENS", "max_tokens", "1", 1),
        ],
        ids=["temp-custom", "temp-zero", "temp-max", "tokens-custom", "tokens-small"],
    )
    def test_from_env_reads_valid_numeric_parameters(
        self,
        env_var: str,
        attr_name: str,
        param_value: str,
        expected: float | int,
    ) -> None:
        """Configuration accepts valid numeric parameter values from environment."""
        env = {
            "GHILLIE_OPENAI_API_KEY": "test-key",
            env_var: param_value,
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = OpenAIStatusModelConfig.from_env()
        actual = getattr(config, attr_name)
        assert actual == expected

    @pytest.mark.parametrize(
        ("attr_name", "expected"),
        [
            ("temperature", 0.3),
            ("max_tokens", 2048),
        ],
        ids=["temperature", "max_tokens"],
    )
    def test_from_env_uses_default_numeric_parameters(
        self, attr_name: str, expected: float | int
    ) -> None:
        """Configuration uses defaults for numeric parameters when not set."""
        env = {"GHILLIE_OPENAI_API_KEY": "test-key"}
        with mock.patch.dict(os.environ, env, clear=True):
            config = OpenAIStatusModelConfig.from_env()
        actual = getattr(config, attr_name)
        assert actual == expected, f"Expected default {attr_name} {expected}"

    @pytest.mark.parametrize(
        ("env_var", "param_name", "value"),
        [
            ("GHILLIE_OPENAI_TEMPERATURE", "temperature", "not-a-number"),
            ("GHILLIE_OPENAI_TEMPERATURE", "temperature", "abc"),
            ("GHILLIE_OPENAI_TEMPERATURE", "temperature", "1.0.0"),
            ("GHILLIE_OPENAI_MAX_TOKENS", "max_tokens", "not-a-number"),
            ("GHILLIE_OPENAI_MAX_TOKENS", "max_tokens", "abc"),
            ("GHILLIE_OPENAI_MAX_TOKENS", "max_tokens", "1.5"),
        ],
        ids=[
            "temp-text",
            "temp-letters",
            "temp-invalid-format",
            "tokens-text",
            "tokens-letters",
            "tokens-float",
        ],
    )
    def test_rejects_non_numeric_parameters(
        self, env_var: str, param_name: str, value: str
    ) -> None:
        """Configuration fails for non-numeric parameter values."""
        import re

        from ghillie.status.errors import StatusModelConfigError

        env = {
            "GHILLIE_OPENAI_API_KEY": "test-key",
            env_var: value,
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            pytest.raises(
                StatusModelConfigError, match=re.compile(param_name, re.IGNORECASE)
            ),
        ):
            OpenAIStatusModelConfig.from_env()

    @pytest.mark.parametrize(
        ("env_var", "param_name", "param_value"),
        [
            ("GHILLIE_OPENAI_TEMPERATURE", "temperature", "2.5"),
            ("GHILLIE_OPENAI_TEMPERATURE", "temperature", "-0.1"),
            ("GHILLIE_OPENAI_MAX_TOKENS", "max_tokens", "0"),
            ("GHILLIE_OPENAI_MAX_TOKENS", "max_tokens", "-100"),
        ],
        ids=["temp-above-max", "temp-negative", "tokens-zero", "tokens-negative"],
    )
    def test_rejects_out_of_range_numeric_parameters(
        self, env_var: str, param_name: str, param_value: str
    ) -> None:
        """Configuration fails for out-of-range numeric parameter values."""
        import re

        from ghillie.status.errors import StatusModelConfigError

        env = {
            "GHILLIE_OPENAI_API_KEY": "test-key",
            env_var: param_value,
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            pytest.raises(
                StatusModelConfigError, match=re.compile(param_name, re.IGNORECASE)
            ),
        ):
            OpenAIStatusModelConfig.from_env()
