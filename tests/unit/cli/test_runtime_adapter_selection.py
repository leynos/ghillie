"""Unit tests for local runtime adapter selection."""

from __future__ import annotations

import pytest

from ghillie.cli.commands.params import RuntimeBackend
from ghillie.cli.runtime_adapters import (
    CuprumRuntimeAdapter,
    PythonApiRuntimeAdapter,
    select_runtime_adapter,
)


def test_select_runtime_adapter_accepts_cuprum() -> None:
    """The documented `cuprum` backend should resolve successfully."""
    adapter = select_runtime_adapter(RuntimeBackend.CUPRUM)
    assert isinstance(adapter, CuprumRuntimeAdapter)
    assert adapter.name == RuntimeBackend.CUPRUM


def test_select_runtime_adapter_accepts_python_api() -> None:
    """The documented `python-api` backend should resolve successfully."""
    adapter = select_runtime_adapter(RuntimeBackend.PYTHON_API)
    assert isinstance(adapter, PythonApiRuntimeAdapter)
    assert adapter.name == RuntimeBackend.PYTHON_API


def test_select_runtime_adapter_rejects_unknown_backend() -> None:
    """Unknown runtime backends should fail fast before any side effects."""
    import typing as typ

    with pytest.raises(ValueError, match="Unsupported runtime backend"):
        select_runtime_adapter(typ.cast("typ.Any", "invalid"))
