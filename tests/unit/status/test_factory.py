"""Unit tests for status model factory."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from ghillie.status.errors import StatusModelConfigError
from ghillie.status.factory import create_status_model
from ghillie.status.mock import MockStatusModel


class TestCreateStatusModelBackendSelection:
    """Tests for backend selection in create_status_model factory."""

    def test_raises_when_backend_missing(self) -> None:
        """Factory raises error when GHILLIE_STATUS_MODEL_BACKEND missing."""
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            pytest.raises(StatusModelConfigError, match="GHILLIE_STATUS_MODEL_BACKEND"),
        ):
            create_status_model()

    def test_raises_on_invalid_backend(self) -> None:
        """Factory raises StatusModelConfigError for unrecognised backend."""
        env = {"GHILLIE_STATUS_MODEL_BACKEND": "invalid-backend"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            pytest.raises(StatusModelConfigError, match="invalid-backend") as exc_info,
        ):
            create_status_model()
        error_msg = str(exc_info.value)
        assert "mock" in error_msg, "Error message should list valid options"
        assert "openai" in error_msg, "Error message should list valid options"

    @pytest.mark.parametrize(
        "backend_value",
        [
            "mock",
            "MOCK",
            "Mock",
            "  mock  ",
        ],
        ids=["lowercase", "uppercase", "mixed-case", "with-whitespace"],
    )
    def test_creates_mock_model_normalised(self, backend_value: str) -> None:
        """Factory creates MockStatusModel with case/whitespace normalisation."""
        env = {"GHILLIE_STATUS_MODEL_BACKEND": backend_value}
        with mock.patch.dict(os.environ, env, clear=True):
            model = create_status_model()
        assert isinstance(model, MockStatusModel), (
            f"Expected MockStatusModel for backend value '{backend_value}'"
        )


class TestCreateStatusModelOpenAIBackend:
    """Tests for OpenAI backend in create_status_model factory."""

    def test_creates_openai_model(self) -> None:
        """Factory creates OpenAIStatusModel for 'openai' backend."""
        from ghillie.status.openai_client import OpenAIStatusModel

        env = {
            "GHILLIE_STATUS_MODEL_BACKEND": "openai",
            "GHILLIE_OPENAI_API_KEY": "test-key-123",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            model = create_status_model()
        assert isinstance(model, OpenAIStatusModel), (
            "Expected OpenAIStatusModel instance"
        )

    def test_openai_model_uses_default_config(self) -> None:
        """OpenAI model uses default configuration when only API key provided."""
        from ghillie.status.openai_client import OpenAIStatusModel

        env = {
            "GHILLIE_STATUS_MODEL_BACKEND": "openai",
            "GHILLIE_OPENAI_API_KEY": "test-key",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            model = create_status_model()
        assert isinstance(model, OpenAIStatusModel)
        assert model.config.temperature == 0.3, "Expected default temperature"
        assert model.config.max_tokens == 2048, "Expected default max_tokens"

    @pytest.mark.parametrize(
        ("env_var", "env_value", "config_attr", "expected_value"),
        [
            ("GHILLIE_OPENAI_TEMPERATURE", "0.7", "temperature", 0.7),
            ("GHILLIE_OPENAI_MAX_TOKENS", "4096", "max_tokens", 4096),
        ],
        ids=["temperature", "max_tokens"],
    )
    def test_openai_model_uses_config_from_env(
        self,
        env_var: str,
        env_value: str,
        config_attr: str,
        expected_value: float | int,
    ) -> None:
        """OpenAI model uses configuration parameters from environment."""
        from ghillie.status.openai_client import OpenAIStatusModel

        env = {
            "GHILLIE_STATUS_MODEL_BACKEND": "openai",
            "GHILLIE_OPENAI_API_KEY": "test-key",
            env_var: env_value,
        }
        with mock.patch.dict(os.environ, env, clear=True):
            model = create_status_model()
        assert isinstance(model, OpenAIStatusModel)
        actual_value = getattr(model.config, config_attr)
        assert actual_value == expected_value, (
            f"Expected {config_attr} {expected_value} from environment"
        )

    def test_openai_model_uses_all_config_from_env(self) -> None:
        """OpenAI model uses all configuration from environment."""
        from ghillie.status.openai_client import OpenAIStatusModel

        env = {
            "GHILLIE_STATUS_MODEL_BACKEND": "openai",
            "GHILLIE_OPENAI_API_KEY": "test-key",
            "GHILLIE_OPENAI_ENDPOINT": "http://localhost:8080/v1/chat/completions",
            "GHILLIE_OPENAI_MODEL": "gpt-4-turbo",
            "GHILLIE_OPENAI_TEMPERATURE": "0.5",
            "GHILLIE_OPENAI_MAX_TOKENS": "1024",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            model = create_status_model()
        assert isinstance(model, OpenAIStatusModel)
        assert model.config.endpoint == "http://localhost:8080/v1/chat/completions"
        assert model.config.model == "gpt-4-turbo"
        assert model.config.temperature == 0.5
        assert model.config.max_tokens == 1024

    def test_openai_backend_requires_api_key(self) -> None:
        """OpenAI backend raises error when API key is missing."""
        from ghillie.status.errors import OpenAIConfigError

        env = {"GHILLIE_STATUS_MODEL_BACKEND": "openai"}
        with (
            mock.patch.dict(os.environ, env, clear=True),
            pytest.raises(OpenAIConfigError, match="GHILLIE_OPENAI_API_KEY"),
        ):
            create_status_model()
