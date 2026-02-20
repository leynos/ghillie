"""Model invocation metrics shared by status model adapters and reporting."""

from __future__ import annotations

import dataclasses as dc


@dc.dataclass(frozen=True, slots=True)
class ModelInvocationMetrics:
    """Token and latency metrics from a single model invocation.

    Attributes
    ----------
    prompt_tokens
        Number of prompt tokens consumed, when known.
    completion_tokens
        Number of completion tokens generated, when known.
    total_tokens
        Total token count for the invocation, when known.
    latency_ms
        Invocation latency in milliseconds, when measured.

    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: float | None = None
