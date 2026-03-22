"""Unit tests for local runtime adapter selection."""

from __future__ import annotations

import pytest

from ghillie.cli.runtime_adapters import (
    CuprumRuntimeAdapter,
    PythonApiRuntimeAdapter,
    select_runtime_adapter,
)


def test_select_runtime_adapter_accepts_cuprum() -> None:
    """The documented `cuprum` backend should resolve successfully."""
    adapter = select_runtime_adapter("cuprum")
    assert isinstance(adapter, CuprumRuntimeAdapter)
    assert adapter.name == "cuprum"


def test_select_runtime_adapter_accepts_python_api() -> None:
    """The documented `python-api` backend should resolve successfully."""
    adapter = select_runtime_adapter("python-api")
    assert isinstance(adapter, PythonApiRuntimeAdapter)
    assert adapter.name == "python-api"


def test_select_runtime_adapter_rejects_unknown_backend() -> None:
    """Unknown runtime backends should fail fast before any side effects."""
    import typing as typ

    with pytest.raises(ValueError, match="Unsupported runtime backend"):
        select_runtime_adapter(typ.cast("typ.Any", "invalid"))
