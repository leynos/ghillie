"""Factory for creating StatusModel implementations from environment configuration."""

from __future__ import annotations

import os
import typing as typ

from ghillie.status.errors import StatusModelConfigError
from ghillie.status.mock import MockStatusModel

if typ.TYPE_CHECKING:
    from ghillie.status.protocol import StatusModel

_VALID_BACKENDS = frozenset({"mock", "openai"})


def create_status_model() -> StatusModel:
    """Create a StatusModel implementation based on environment configuration.

    Reads the following environment variables:

    - ``GHILLIE_STATUS_MODEL_BACKEND``: Required. Either 'mock' or 'openai'.

    For 'openai' backend, also reads:

    - ``GHILLIE_OPENAI_API_KEY``: Required API key
    - ``GHILLIE_OPENAI_ENDPOINT``: Optional endpoint override
    - ``GHILLIE_OPENAI_MODEL``: Optional model override
    - ``GHILLIE_OPENAI_TEMPERATURE``: Optional temperature (0.0-2.0)
    - ``GHILLIE_OPENAI_MAX_TOKENS``: Optional max tokens (positive integer)

    Returns
    -------
    StatusModel
        Configured status model implementation.

    Raises
    ------
    StatusModelConfigError
        If the backend environment variable is missing or invalid.
    OpenAIConfigError
        If OpenAI backend is selected but configuration is invalid.

    Examples
    --------
    >>> import os
    >>> os.environ["GHILLIE_STATUS_MODEL_BACKEND"] = "mock"
    >>> model = create_status_model()
    >>> isinstance(model, MockStatusModel)
    True

    """
    raw_backend = os.environ.get("GHILLIE_STATUS_MODEL_BACKEND")
    if raw_backend is None:
        raise StatusModelConfigError.missing_backend()

    backend = raw_backend.strip().lower()
    if backend not in _VALID_BACKENDS:
        raise StatusModelConfigError.invalid_backend(raw_backend)

    if backend == "mock":
        return MockStatusModel()

    # backend == "openai"
    from ghillie.status.config import OpenAIStatusModelConfig
    from ghillie.status.openai_client import OpenAIStatusModel

    config = OpenAIStatusModelConfig.from_env()
    return OpenAIStatusModel(config)
