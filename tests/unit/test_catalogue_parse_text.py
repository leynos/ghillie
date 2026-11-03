"""Parsing catalogue text received over HTTP.

Uploaded text is untrusted. Anchors and aliases are rejected before the loader
expands them, so an alias bomb cannot allocate exponentially even when its
serialized form is under the 1 MiB request limit.
"""

import pytest

from ghillie.catalogue import CatalogueValidationError
from ghillie.catalogue.loader import parse_catalogue_text

_VALID = """
version: 1
projects:
  - key: alpha
    name: Alpha
    components:
      - key: alpha-api
        name: Alpha API
        type: service
        lifecycle: active
        repository:
          owner: org
          name: alpha
          default_branch: main
"""


def test_parse_catalogue_text_accepts_a_valid_document() -> None:
    """The happy path returns a validated catalogue."""
    catalogue = parse_catalogue_text(_VALID)

    assert catalogue.version == 1
    assert catalogue.projects[0].key == "alpha"


def test_parse_catalogue_text_rejects_empty_text() -> None:
    """An empty document is not a catalogue."""
    with pytest.raises(CatalogueValidationError, match="empty"):
        parse_catalogue_text("")


def test_parse_catalogue_text_rejects_invalid_yaml() -> None:
    """Malformed YAML is reported as a catalogue validation failure."""
    with pytest.raises(CatalogueValidationError, match="failed to parse YAML"):
        parse_catalogue_text("version: [unclosed")


def test_parse_catalogue_text_rejects_duplicate_keys() -> None:
    """Duplicate mapping keys are ambiguous and therefore rejected."""
    with pytest.raises(CatalogueValidationError, match="failed to parse YAML"):
        parse_catalogue_text("version: 1\nversion: 2\nprojects: []\n")


def test_parse_catalogue_text_rejects_anchors() -> None:
    """A document that defines an anchor is rejected before expansion."""
    document = """
version: 1
projects: &projects []
"""
    with pytest.raises(CatalogueValidationError, match="anchors or aliases"):
        parse_catalogue_text(document)


def test_parse_catalogue_text_rejects_aliases() -> None:
    """A document that only uses an alias is rejected before expansion."""
    document = """
first: &shared value
second: *shared
version: 1
projects: []
"""
    with pytest.raises(CatalogueValidationError, match="anchors or aliases"):
        parse_catalogue_text(document)


def test_parse_catalogue_text_rejects_an_alias_bomb_under_one_mib() -> None:
    """A small serialized alias bomb is rejected without expanding it."""
    lines = ["a0: &a0 [x, x, x, x, x, x, x, x, x, x]"]
    for level in range(1, 8):
        previous = f"*a{level - 1}"
        repeated = ", ".join([previous] * 10)
        lines.append(f"a{level}: &a{level} [{repeated}]")
    lines.extend(["version: 1", "projects: []"])
    document = "\n".join(lines)

    assert len(document.encode("utf-8")) < 1_048_576
    with pytest.raises(CatalogueValidationError, match="anchors or aliases"):
        parse_catalogue_text(document)


def test_parse_catalogue_text_accepts_a_byte_order_mark() -> None:
    """A UTF-8 BOM is tolerated, as the CLI reads files with ``utf-8-sig``."""
    catalogue = parse_catalogue_text("﻿" + _VALID)

    assert catalogue.version == 1


def test_parse_catalogue_text_rejects_a_schema_failure() -> None:
    """A structurally invalid document is a schema failure."""
    with pytest.raises(CatalogueValidationError, match="schema validation failed"):
        parse_catalogue_text("projects: []\n")
