"""Runtime adapter selection for local stack orchestration."""

from __future__ import annotations

import dataclasses
import typing as typ

from ghillie.cli.commands.params import RuntimeBackend


class LocalRuntimeAdapter(typ.Protocol):
    """Protocol implemented by local runtime adapter placeholders."""

    name: RuntimeBackend


@dataclasses.dataclass(frozen=True, slots=True)
class CuprumRuntimeAdapter:
    """Placeholder adapter for shell-oriented local orchestration."""

    name: RuntimeBackend = RuntimeBackend.CUPRUM


@dataclasses.dataclass(frozen=True, slots=True)
class PythonApiRuntimeAdapter:
    """Placeholder adapter for direct Python integrations."""

    name: RuntimeBackend = RuntimeBackend.PYTHON_API


def select_runtime_adapter(backend: RuntimeBackend) -> LocalRuntimeAdapter:
    """Select a local runtime adapter by the documented backend name."""
    match backend:
        case "cuprum":
            return CuprumRuntimeAdapter()
        case "python-api":
            return PythonApiRuntimeAdapter()
        case _:
            msg = f"Unsupported runtime backend: {backend}"
            raise ValueError(msg)
