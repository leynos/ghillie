"""Parsing catalogue text received over HTTP.

Uploaded text is untrusted. Anchors and aliases are rejected before the loader
expands them, so an alias bomb cannot allocate exponentially even when its
serialized form is under the 1 MiB request limit.
"""

import typing as typ

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ghillie.catalogue import CatalogueValidationError
from ghillie.catalogue.loader import (
    _MAX_YAML_DEPTH,
    load_catalogue,
    parse_catalogue_text,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

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

    assert catalogue.version == 1, "catalogue should declare version 1"
    assert catalogue.projects[0].key == "alpha", (
        "catalogue should carry the project key"
    )


def test_load_catalogue_rejects_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    """Undecodable bytes are a validation failure, not an uncaught traceback."""
    path = tmp_path / "invalid.yaml"
    path.write_bytes(b"version: 1\n# \xff\xfe\n")

    with pytest.raises(CatalogueValidationError, match="failed to parse YAML"):
        load_catalogue(path)


def test_parse_catalogue_text_rejects_empty_text() -> None:
    """An empty document is not a catalogue."""
    with pytest.raises(CatalogueValidationError, match="empty"):
        parse_catalogue_text("")


def test_parse_catalogue_text_rejects_excessive_nesting() -> None:
    """A deeply nested document is rejected before a recursive compose.

    The event scan runs before ``yaml.load`` composes the document, so a
    payload built from nested flow collections cannot exhaust the interpreter
    stack and surface as an unhandled 500.
    """
    document = "[" * 200 + "]" * 200

    with pytest.raises(CatalogueValidationError, match="deeper than"):
        parse_catalogue_text(document)


def test_parse_catalogue_text_rejects_invalid_yaml() -> None:
    """Malformed YAML is reported as a catalogue validation failure."""
    with pytest.raises(CatalogueValidationError, match="failed to parse YAML"):
        parse_catalogue_text("version: [unclosed")


def test_parse_catalogue_text_rejects_duplicate_keys() -> None:
    """Duplicate mapping keys are ambiguous and therefore rejected."""
    with pytest.raises(CatalogueValidationError, match="failed to parse YAML"):
        parse_catalogue_text("version: 1\nversion: 2\nprojects: []\n")


def test_parse_catalogue_text_rejects_an_impossible_yaml_timestamp() -> None:
    """A scalar the resolver cannot build is a validation failure.

    YAML 1.2 resolves ``2026-13-01`` as a timestamp and the constructor then
    raises ``ValueError`` for the impossible month. That is a property of the
    untrusted text, like malformed YAML, so it must take the same validation
    path instead of escaping as an unhandled error.
    """
    with pytest.raises(CatalogueValidationError, match="failed to parse YAML"):
        parse_catalogue_text("version: 2026-13-01\nprojects: []\n")


@pytest.mark.parametrize(
    "document",
    [
        pytest.param("version: !!bool invalid\n", id="invalid-boolean"),
        pytest.param("? [[nested]]\n: 1\n", id="unhashable-mapping-key"),
        pytest.param(
            "version: 9999-12-31T23:59:59.9999999Z\n",
            id="overflowing-timestamp",
        ),
    ],
)
def test_parse_catalogue_text_rejects_constructor_failures(document: str) -> None:
    """A scalar or key the constructor cannot build is a validation failure.

    ruamel reports these as ``KeyError``, ``TypeError`` and ``OverflowError``
    rather than a ``YAMLError``: an invalid ``!!bool`` has no lookup entry, a
    nested sequence cannot be hashed as a mapping key, and a timestamp that
    rounds past year 9999 overflows ``datetime``. Each document passes the
    anchor and depth scan, so without this boundary one crafted upload would
    escape the import endpoint as a 500 instead of the documented 422.
    """
    with pytest.raises(CatalogueValidationError, match="failed to parse YAML"):
        parse_catalogue_text(document)


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(
            "version: 1\nprojects: &projects []\n",
            id="defines-an-anchor",
        ),
        pytest.param(
            "first: &shared value\nsecond: *shared\nversion: 1\nprojects: []\n",
            id="only-uses-an-alias",
        ),
    ],
)
def test_parse_catalogue_text_rejects_anchors_and_aliases(document: str) -> None:
    """Anchor and alias documents are rejected before expansion."""
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

    assert len(document.encode("utf-8")) < 1_048_576, (
        "alias bomb should serialize under one mebibyte"
    )
    with pytest.raises(CatalogueValidationError, match="anchors or aliases"):
        parse_catalogue_text(document)


def test_parse_catalogue_text_accepts_a_byte_order_mark() -> None:
    """A UTF-8 BOM is tolerated, as the CLI reads files with ``utf-8-sig``."""
    catalogue = parse_catalogue_text("\ufeff" + _VALID)

    assert catalogue.version == 1, "BOM should be stripped"


_CONSTRUCTOR_PROBES = st.sampled_from(
    [
        "version: !!bool invalid\n",
        "version: !!int not-a-number\n",
        "version: !!float not-a-number\n",
        "version: !!timestamp 2026-13-45\n",
        "version: 9999-12-31T23:59:59.9999999Z\n",
        "? [[nested]]\n: 1\n",
        "version: &a [*a]\n",
        "version: *missing\n",
    ]
)
"""Fragments that reach a constructor rather than failing the YAML scanner."""


@st.composite
def _catalogue_documents(
    draw: st.DrawFn,
) -> str:
    """Draw arbitrary text, or a constructor-triggering fragment in context."""
    if draw(st.booleans()):
        return draw(st.text(max_size=512))
    prefix = draw(st.text(max_size=128))
    probe = draw(_CONSTRUCTOR_PROBES)
    suffix = draw(st.text(max_size=128))
    return f"{prefix}\n{probe}{suffix}"


# Every property here parses YAML, so its runtime grows with the generated
# document and with host load. The deadline measures wall-clock time, not
# correctness, and a busy machine would otherwise report a flake.
_NO_DEADLINE = settings(deadline=None)


@given(document=_catalogue_documents())
@_NO_DEADLINE
def test_property_parse_raises_only_validation_errors(document: str) -> None:
    """Invariant: any text either parses or fails validation, never another way.

    The endpoint receives untrusted text, so every way the loader can refuse a
    document -- a YAML error, a constructor rejection, a depth or schema
    failure -- must leave as :class:`CatalogueValidationError`. Any other
    exception escapes as a 500 and tells the caller nothing it can act on.
    """
    try:
        catalogue = parse_catalogue_text(document)
    except CatalogueValidationError:
        return
    assert catalogue.version >= 1, catalogue


def test_parse_catalogue_text_rejects_a_schema_failure() -> None:
    """A structurally invalid document is a schema failure."""
    with pytest.raises(CatalogueValidationError, match="schema validation failed"):
        parse_catalogue_text("projects: []\n")


# Pinned independently of ``_MAX_YAML_DEPTH``, so a change to the loader's
# limit fails the guard test below instead of silently moving the boundary.
_PINNED_MAX_YAML_DEPTH = 64


def _nested_flow_document(depth: int) -> str:
    """Return a document of *depth* nested flow sequences.

    Flow collections never repeat a mapping key, so the only reason the parser
    may reject one of these is the nesting guard or the catalogue schema.
    """
    return "[" * depth + "]" * depth


def _nested_mapping_document(depth: int) -> str:
    """Return a document of *depth* nested flow mappings with distinct keys."""
    document = "value"
    for level in range(depth):
        document = f"{{key{level}: {document}}}"
    return document


def _nested_mixed_document(depth: int) -> str:
    """Return a document alternating nested sequences and mappings."""
    document = "value"
    for level in range(depth):
        document = f"[{document}]" if level % 2 == 0 else f"{{key{level}: {document}}}"
    return document


_DOCUMENT_BUILDERS = (
    _nested_flow_document,
    _nested_mapping_document,
    _nested_mixed_document,
)


def _assert_depth_guard_admits(document: str) -> None:
    """Fail if the nesting guard, rather than the schema, rejected *document*.

    A nested flow collection is never a valid catalogue, so the schema
    rejection is the expected outcome; reaching it proves the depth guard
    admitted the document first.
    """
    with pytest.raises(CatalogueValidationError, match="schema validation failed"):
        parse_catalogue_text(document)


def test_the_pinned_depth_matches_the_loader_limit() -> None:
    """The literal boundary below is the loader's limit, not a copy of it.

    Pinning the number here means a change to ``_MAX_YAML_DEPTH`` fails this
    test instead of silently moving every boundary case with the constant.
    """
    assert _MAX_YAML_DEPTH == _PINNED_MAX_YAML_DEPTH, (
        "the loader's depth limit changed; re-pin the boundary cases"
    )


@given(
    depth=st.integers(min_value=1, max_value=_PINNED_MAX_YAML_DEPTH),
    build=st.sampled_from(_DOCUMENT_BUILDERS),
)
@_NO_DEADLINE
def test_property_documents_within_the_depth_limit_pass_the_guard(
    depth: int, build: typ.Callable[[int], str]
) -> None:
    """Invariant: nesting of at most 64 levels never trips the depth guard.

    A document is rejected for depth if and only if it nests more than 64
    collections, so every depth up to the limit must reach the schema check
    instead, in each collection form the event scan counts.
    """
    _assert_depth_guard_admits(build(depth))


@given(
    depth=st.integers(min_value=_PINNED_MAX_YAML_DEPTH + 1, max_value=500),
    build=st.sampled_from(_DOCUMENT_BUILDERS),
)
@_NO_DEADLINE
def test_property_documents_beyond_the_depth_limit_are_rejected(
    depth: int, build: typ.Callable[[int], str]
) -> None:
    """Invariant: nesting beyond 64 levels is always a validation failure."""
    with pytest.raises(CatalogueValidationError, match="deeper than"):
        parse_catalogue_text(build(depth))


@pytest.mark.parametrize("build", _DOCUMENT_BUILDERS, ids=lambda b: b.__name__)
@pytest.mark.parametrize(
    ("depth", "expected_message"),
    [
        pytest.param(_PINNED_MAX_YAML_DEPTH, None, id="at-the-limit"),
        pytest.param(_PINNED_MAX_YAML_DEPTH + 1, "deeper than", id="one-past"),
    ],
)
def test_depth_guard_boundary(
    build: typ.Callable[[int], str], depth: int, expected_message: str | None
) -> None:
    """The guard admits exactly 64 levels and rejects the sixty-fifth."""
    document = build(depth)

    if expected_message is None:
        _assert_depth_guard_admits(document)
        return
    with pytest.raises(CatalogueValidationError, match=expected_message):
        parse_catalogue_text(document)
