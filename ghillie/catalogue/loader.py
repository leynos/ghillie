"""YAML loaders for catalogue configuration files."""

from __future__ import annotations

from pathlib import Path

import msgspec
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .models import Catalogue
from .validation import CatalogueValidationError, validate_catalogue

YAML_VERSION = (1, 2)


def lint_catalogue(path: Path | str) -> Catalogue:
    """Load and validate a YAML catalogue file in one step."""
    return load_catalogue(path)


def load_catalogue(path: Path | str) -> Catalogue:
    """Parse a YAML catalogue file using a YAML 1.2 compliant loader."""
    yaml = _yaml()
    path_obj = Path(path)

    try:
        loaded = yaml.load(path_obj.read_text(encoding="utf-8"))
    except (OSError, YAMLError) as exc:
        raise CatalogueValidationError([f"failed to parse YAML: {exc}"]) from exc

    if loaded is None:
        raise CatalogueValidationError(["catalogue file is empty"])

    try:
        catalogue = msgspec.convert(loaded, type=Catalogue)
    except msgspec.ValidationError as exc:
        raise CatalogueValidationError([f"schema validation failed: {exc}"]) from exc

    return validate_catalogue(catalogue)


def _yaml() -> YAML:
    yaml = YAML(typ="safe")
    yaml.version = YAML_VERSION
    yaml.allow_duplicate_keys = False
    yaml.default_flow_style = False
    return yaml
