"""Configuration for OpenAI status model client."""

from __future__ import annotations

import dataclasses
import os

from ghillie.status.errors import OpenAIConfigError


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
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    model: str = "gpt-5.1-thinking"
    timeout_s: float = 120.0
    temperature: float = 0.3
    max_tokens: int = 2048

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
        api_key = os.environ.get("GHILLIE_OPENAI_API_KEY", "").strip()
        if not api_key:
            raise OpenAIConfigError.missing_api_key()

        endpoint = os.environ.get(
            "GHILLIE_OPENAI_ENDPOINT",
            "https://api.openai.com/v1/chat/completions",
        )
        model = os.environ.get("GHILLIE_OPENAI_MODEL", "gpt-5.1-thinking")

        return cls(api_key=api_key, endpoint=endpoint, model=model)
