"""YAML loaders for catalogue configuration files."""

import io
from pathlib import Path

import msgspec
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.events import (
    AliasEvent,
    MappingEndEvent,
    MappingStartEvent,
    SequenceEndEvent,
    SequenceStartEvent,
)

from .models import Catalogue
from .validation import CatalogueValidationError, validate_catalogue

YAML_VERSION = (1, 2)

_BOM = "\ufeff"
_MAX_YAML_DEPTH = 64
"""Deepest collection nesting the event scan accepts.

The scan runs before ``yaml.load`` composes the document. Composition recurses
once per collection level, so a payload made of nested flow collections could
otherwise exhaust the interpreter stack and surface as an unhandled 500.
"""


def lint_catalogue(path: Path | str) -> Catalogue:
    """Load and validate a YAML catalogue file in one step."""
    return load_catalogue(path)


def load_catalogue(path: Path | str) -> Catalogue:
    """Parse a YAML catalogue file using a YAML 1.2 compliant loader."""
    path_obj = Path(path)

    try:
        text = path_obj.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        # A file that cannot be read or decoded is an input problem, so it
        # takes the same validation path as malformed YAML rather than
        # escaping as a traceback.
        raise CatalogueValidationError([f"failed to parse YAML: {exc}"]) from exc

    return parse_catalogue_text(text)


def parse_catalogue_text(text: str) -> Catalogue:
    """Parse and validate catalogue YAML supplied as a string.

    The text is untrusted: documents that define anchors, use aliases, or nest
    collections beyond :data:`_MAX_YAML_DEPTH` levels are rejected before the
    loader expands or composes them. That keeps an alias bomb from allocating
    exponentially and a deeply nested document from exhausting the stack,
    both within the request-size limit.

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

    _reject_unsafe_structure(text)

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


def _reject_unsafe_structure(text: str) -> None:
    """Reject anchors, aliases, and collections nested beyond the limit.

    Parsing to events does not compose the document, so this scan can inspect
    an untrusted payload before the recursive constructor runs.
    """
    yaml = _yaml()
    depth = 0
    try:
        for event in yaml.parse(io.StringIO(text)):
            if isinstance(event, AliasEvent) or getattr(event, "anchor", None):
                message = "catalogue must not use YAML anchors or aliases"
                raise CatalogueValidationError([message])
            if isinstance(event, (MappingStartEvent, SequenceStartEvent)):
                depth += 1
                if depth > _MAX_YAML_DEPTH:
                    message = (
                        "catalogue must not nest YAML collections deeper than "
                        f"{_MAX_YAML_DEPTH} levels"
                    )
                    raise CatalogueValidationError([message])
            elif isinstance(event, (MappingEndEvent, SequenceEndEvent)):
                depth -= 1
    except YAMLError as exc:
        raise CatalogueValidationError([f"failed to parse YAML: {exc}"]) from exc


def _yaml() -> YAML:
    yaml = YAML(typ="safe")
    yaml.version = YAML_VERSION
    yaml.allow_duplicate_keys = False
    yaml.default_flow_style = False
    return yaml
