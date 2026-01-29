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
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(StatusModelConfigError) as exc_info:
                create_status_model()
            assert "GHILLIE_STATUS_MODEL_BACKEND" in str(exc_info.value), (
                "Error message should reference missing env var"
            )

    def test_raises_on_invalid_backend(self) -> None:
        """Factory raises StatusModelConfigError for unrecognized backend."""
        env = {"GHILLIE_STATUS_MODEL_BACKEND": "invalid-backend"}
        with mock.patch.dict(os.environ, env, clear=True):
            with pytest.raises(StatusModelConfigError) as exc_info:
                create_status_model()
            error_msg = str(exc_info.value)
            assert "invalid-backend" in error_msg, (
                "Error message should include the invalid backend name"
            )
            assert "mock" in error_msg, "Error message should list valid options"
            assert "openai" in error_msg, "Error message should list valid options"

    def test_creates_mock_model(self) -> None:
        """Factory creates MockStatusModel for 'mock' backend."""
        env = {"GHILLIE_STATUS_MODEL_BACKEND": "mock"}
        with mock.patch.dict(os.environ, env, clear=True):
            model = create_status_model()
        assert isinstance(model, MockStatusModel), "Expected MockStatusModel instance"

    def test_creates_mock_model_case_insensitive(self) -> None:
        """Factory handles case-insensitive backend names."""
        env = {"GHILLIE_STATUS_MODEL_BACKEND": "MOCK"}
        with mock.patch.dict(os.environ, env, clear=True):
            model = create_status_model()
        assert isinstance(model, MockStatusModel), (
            "Expected MockStatusModel for uppercase 'MOCK'"
        )

    def test_creates_mock_model_mixed_case(self) -> None:
        """Factory handles mixed case backend names."""
        env = {"GHILLIE_STATUS_MODEL_BACKEND": "Mock"}
        with mock.patch.dict(os.environ, env, clear=True):
            model = create_status_model()
        assert isinstance(model, MockStatusModel), (
            "Expected MockStatusModel for mixed case 'Mock'"
        )

    def test_creates_mock_model_with_whitespace(self) -> None:
        """Factory strips whitespace from backend name."""
        env = {"GHILLIE_STATUS_MODEL_BACKEND": "  mock  "}
        with mock.patch.dict(os.environ, env, clear=True):
            model = create_status_model()
        assert isinstance(model, MockStatusModel), (
            "Expected MockStatusModel with surrounding whitespace"
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
        assert model._config.temperature == 0.3, "Expected default temperature"
        assert model._config.max_tokens == 2048, "Expected default max_tokens"

    def test_openai_model_uses_temperature_from_env(self) -> None:
        """OpenAI model uses temperature from environment."""
        from ghillie.status.openai_client import OpenAIStatusModel

        env = {
            "GHILLIE_STATUS_MODEL_BACKEND": "openai",
            "GHILLIE_OPENAI_API_KEY": "test-key",
            "GHILLIE_OPENAI_TEMPERATURE": "0.7",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            model = create_status_model()
        assert isinstance(model, OpenAIStatusModel)
        assert model._config.temperature == 0.7, (
            "Expected temperature 0.7 from environment"
        )

    def test_openai_model_uses_max_tokens_from_env(self) -> None:
        """OpenAI model uses max_tokens from environment."""
        from ghillie.status.openai_client import OpenAIStatusModel

        env = {
            "GHILLIE_STATUS_MODEL_BACKEND": "openai",
            "GHILLIE_OPENAI_API_KEY": "test-key",
            "GHILLIE_OPENAI_MAX_TOKENS": "4096",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            model = create_status_model()
        assert isinstance(model, OpenAIStatusModel)
        assert model._config.max_tokens == 4096, (
            "Expected max_tokens 4096 from environment"
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
        assert model._config.endpoint == "http://localhost:8080/v1/chat/completions"
        assert model._config.model == "gpt-4-turbo"
        assert model._config.temperature == 0.5
        assert model._config.max_tokens == 1024

    def test_openai_backend_requires_api_key(self) -> None:
        """OpenAI backend raises error when API key is missing."""
        from ghillie.status.errors import OpenAIConfigError

        env = {"GHILLIE_STATUS_MODEL_BACKEND": "openai"}
        with mock.patch.dict(os.environ, env, clear=True):
            with pytest.raises(OpenAIConfigError) as exc_info:
                create_status_model()
            assert "GHILLIE_OPENAI_API_KEY" in str(exc_info.value)
