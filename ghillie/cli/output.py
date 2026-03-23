"""Output formatting helpers for operator CLI placeholders."""

from __future__ import annotations

import io
import json
import typing as typ

from ruamel.yaml import YAML

if typ.TYPE_CHECKING:
    from .config import OutputFormat


def render_output(payload: typ.Mapping[str, object], *, output: OutputFormat) -> str:
    """Render one CLI payload according to the selected output format."""
    if output == "json":
        return json.dumps(payload, sort_keys=True)
    if output == "yaml":
        buffer = io.StringIO()
        yaml = YAML(typ="safe")
        yaml.default_flow_style = False
        yaml.dump(dict(payload), buffer)
        return buffer.getvalue().strip()
    return "\n".join(f"{key}: {value}" for key, value in payload.items())
