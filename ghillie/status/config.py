"""Configuration for OpenAI status model client."""

from __future__ import annotations

import dataclasses
import os

from ghillie.status.errors import OpenAIConfigError

# Default configuration values - single source of truth
_DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_DEFAULT_MODEL = "gpt-5.1-thinking"
_DEFAULT_TIMEOUT_S = 120.0
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_TOKENS = 2048


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

    @classmethod
    def from_env(cls) -> OpenAIStatusModelConfig:
        """Build configuration from environment variables.

        Reads the following environment variables:

        - ``GHILLIE_OPENAI_API_KEY``: Required API key
        - ``GHILLIE_OPENAI_ENDPOINT``: Optional endpoint override
        - ``GHILLIE_OPENAI_MODEL``: Optional model override

        Returns
        -------
        OpenAIStatusModelConfig
            Configuration instance with values from environment.

        Raises
        ------
        OpenAIConfigError
            If required environment variables are missing or invalid.

        """
        raw_api_key = os.environ.get("GHILLIE_OPENAI_API_KEY")
        if raw_api_key is None:
            raise OpenAIConfigError.missing_api_key()
        api_key = raw_api_key.strip()
        if not api_key:
            raise OpenAIConfigError.empty_api_key()

        endpoint = os.environ.get("GHILLIE_OPENAI_ENDPOINT", _DEFAULT_ENDPOINT)
        model = os.environ.get("GHILLIE_OPENAI_MODEL", _DEFAULT_MODEL)

        return cls(api_key=api_key, endpoint=endpoint, model=model)
