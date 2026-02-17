"""Unit tests for model invocation metrics value object."""

from __future__ import annotations

import dataclasses as dc

import pytest

from ghillie.status.metrics import ModelInvocationMetrics


class TestModelInvocationMetrics:
    """Tests for ``ModelInvocationMetrics`` construction and immutability."""

    def test_constructs_with_explicit_values(self) -> None:
        """Constructor stores provided values verbatim."""
        metrics = ModelInvocationMetrics(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=42.5,
        )

        assert metrics.prompt_tokens == 100
        assert metrics.completion_tokens == 50
        assert metrics.total_tokens == 150
        assert metrics.latency_ms == 42.5

    def test_defaults_to_none(self) -> None:
        """All fields default to ``None`` when omitted."""
        metrics = ModelInvocationMetrics()

        assert metrics.prompt_tokens is None
        assert metrics.completion_tokens is None
        assert metrics.total_tokens is None
        assert metrics.latency_ms is None

    def test_is_frozen(self) -> None:
        """Instances are immutable after construction."""
        metrics = ModelInvocationMetrics(prompt_tokens=1)

        with pytest.raises(dc.FrozenInstanceError):
            metrics.prompt_tokens = 2  # type: ignore[misc]
