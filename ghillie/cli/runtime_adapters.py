"""Runtime adapter selection for local stack orchestration."""

from __future__ import annotations

import dataclasses
import typing as typ

RuntimeBackend = typ.Literal["cuprum", "python-api"]


class LocalRuntimeAdapter(typ.Protocol):
    """Protocol implemented by local runtime adapter placeholders."""

    name: RuntimeBackend


@dataclasses.dataclass(frozen=True, slots=True)
class CuprumRuntimeAdapter:
    """Placeholder adapter for shell-oriented local orchestration."""

    name: RuntimeBackend = "cuprum"


@dataclasses.dataclass(frozen=True, slots=True)
class PythonApiRuntimeAdapter:
    """Placeholder adapter for direct Python integrations."""

    name: RuntimeBackend = "python-api"


def select_runtime_adapter(backend: str) -> LocalRuntimeAdapter:
    """Select a local runtime adapter by the documented backend name."""
    if backend == "cuprum":
        return CuprumRuntimeAdapter()
    if backend == "python-api":
        return PythonApiRuntimeAdapter()
    msg = f"Unsupported runtime backend: {backend}"
    raise ValueError(msg)
