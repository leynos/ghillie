"""Configuration for OpenAI status model client."""

from __future__ import annotations

import dataclasses
import os

from ghillie.status.errors import OpenAIConfigError, StatusModelConfigError

# Default configuration values - single source of truth
_DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1-thinking"
_DEFAULT_TIMEOUT_S = 120.0
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_TOKENS = 2048

# Validation bounds for temperature (OpenAI API range)
_MIN_TEMPERATURE = 0.0
_MAX_TEMPERATURE = 2.0


@dataclasses.dataclass(frozen=True, slots=True)
class OpenAIStatusModelConfig:
    """Configuration for OpenAI-compatible status model client.

    Attributes
    ----------
    api_key
        API key for authentication with the OpenAI API.
    endpoint
        Chat completions endpoint URL.
    model
        Model identifier to use for completions.
    timeout_s
        Request timeout in seconds.
    temperature
        Sampling temperature (0.0 to 2.0).
    max_tokens
        Maximum tokens in the completion response.

    """

    api_key: str
    endpoint: str = _DEFAULT_ENDPOINT
    model: str = _DEFAULT_MODEL
    timeout_s: float = _DEFAULT_TIMEOUT_S
    temperature: float = _DEFAULT_TEMPERATURE
    max_tokens: int = _DEFAULT_MAX_TOKENS

    @staticmethod
    def _parse_temperature_from_env() -> float:
        """Parse and validate temperature from environment.

        Returns
        -------
        float
            Validated temperature value or default.

        Raises
        ------
        StatusModelConfigError
            If temperature value is invalid.

        """
        raw_temperature = os.environ.get("GHILLIE_OPENAI_TEMPERATURE")
        if raw_temperature is None:
            return _DEFAULT_TEMPERATURE

        try:
            temperature = float(raw_temperature)
        except ValueError as exc:
            raise StatusModelConfigError.invalid_temperature(raw_temperature) from exc

        if not _MIN_TEMPERATURE <= temperature <= _MAX_TEMPERATURE:
            raise StatusModelConfigError.invalid_temperature(raw_temperature)

        return temperature

    @staticmethod
    def _parse_max_tokens_from_env() -> int:
        """Parse and validate max_tokens from environment.

        Returns
        -------
        int
            Validated max_tokens value or default.

        Raises
        ------
        StatusModelConfigError
            If max_tokens value is invalid.

        """
        raw_max_tokens = os.environ.get("GHILLIE_OPENAI_MAX_TOKENS")
        if raw_max_tokens is None:
            return _DEFAULT_MAX_TOKENS

        try:
            max_tokens = int(raw_max_tokens)
        except ValueError as exc:
            raise StatusModelConfigError.invalid_max_tokens(raw_max_tokens) from exc

        if max_tokens <= 0:
            raise StatusModelConfigError.invalid_max_tokens(raw_max_tokens)

        return max_tokens

    @classmethod
    def from_env(cls) -> OpenAIStatusModelConfig:
        """Build configuration from environment variables.

        Reads the following environment variables:

        - ``GHILLIE_OPENAI_API_KEY``: Required API key
        - ``GHILLIE_OPENAI_ENDPOINT``: Optional endpoint override
        - ``GHILLIE_OPENAI_MODEL``: Optional model override
        - ``GHILLIE_OPENAI_TEMPERATURE``: Optional temperature (0.0 to 2.0)
        - ``GHILLIE_OPENAI_MAX_TOKENS``: Optional max tokens (positive integer)

        Returns
        -------
        OpenAIStatusModelConfig
            Configuration instance with values from environment.

        Raises
        ------
        OpenAIConfigError
            If required environment variables are missing or invalid.
        StatusModelConfigError
            If temperature or max_tokens values are invalid.

        """
        raw_api_key = os.environ.get("GHILLIE_OPENAI_API_KEY")
        if raw_api_key is None:
            raise OpenAIConfigError.missing_api_key()
        api_key = raw_api_key.strip()
        if not api_key:
            raise OpenAIConfigError.empty_api_key()

        endpoint = os.environ.get("GHILLIE_OPENAI_ENDPOINT", _DEFAULT_ENDPOINT)
        model = os.environ.get("GHILLIE_OPENAI_MODEL", _DEFAULT_MODEL)

        temperature = cls._parse_temperature_from_env()
        max_tokens = cls._parse_max_tokens_from_env()

        return cls(
            api_key=api_key,
            endpoint=endpoint,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
