"""YAML loaders for catalogue configuration files."""

import io
from pathlib import Path

import msgspec
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.events import AliasEvent

from .models import Catalogue
from .validation import CatalogueValidationError, validate_catalogue

YAML_VERSION = (1, 2)

_BOM = "﻿"


def lint_catalogue(path: Path | str) -> Catalogue:
    """Load and validate a YAML catalogue file in one step."""
    return load_catalogue(path)


def load_catalogue(path: Path | str) -> Catalogue:
    """Parse a YAML catalogue file using a YAML 1.2 compliant loader."""
    path_obj = Path(path)

    try:
        text = path_obj.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogueValidationError([f"failed to parse YAML: {exc}"]) from exc

    return parse_catalogue_text(text)


def parse_catalogue_text(text: str) -> Catalogue:
    """Parse and validate catalogue YAML supplied as a string.

    The text is untrusted: documents that define anchors or use aliases are
    rejected before the loader can expand them, which keeps an alias bomb from
    allocating exponentially within the request-size limit.

    Parameters
    ----------
    text:
        Raw YAML document text.

    Returns
    -------
    Catalogue
        The parsed and structurally validated catalogue.

    Raises
    ------
    CatalogueValidationError
        If the text is not YAML, contains anchors or aliases, is empty, or
        fails schema or structural validation.

    """
    if text.startswith(_BOM):
        text = text.removeprefix(_BOM)

    _reject_anchors_and_aliases(text)

    yaml = _yaml()
    try:
        loaded = yaml.load(text)
    except YAMLError as exc:
        raise CatalogueValidationError([f"failed to parse YAML: {exc}"]) from exc

    if loaded is None:
        raise CatalogueValidationError(["catalogue file is empty"])

    try:
        catalogue = msgspec.convert(loaded, type=Catalogue)
    except msgspec.ValidationError as exc:
        raise CatalogueValidationError([f"schema validation failed: {exc}"]) from exc

    return validate_catalogue(catalogue)


def _reject_anchors_and_aliases(text: str) -> None:
    """Scan YAML events and reject any anchor definition or alias use."""
    yaml = _yaml()
    try:
        for event in yaml.parse(io.StringIO(text)):
            if isinstance(event, AliasEvent) or getattr(event, "anchor", None):
                message = "catalogue must not use YAML anchors or aliases"
                raise CatalogueValidationError([message])
    except YAMLError as exc:
        raise CatalogueValidationError([f"failed to parse YAML: {exc}"]) from exc


def _yaml() -> YAML:
    yaml = YAML(typ="safe")
    yaml.version = YAML_VERSION
    yaml.allow_duplicate_keys = False
    yaml.default_flow_style = False
    return yaml
