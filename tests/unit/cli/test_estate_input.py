"""Local import preparation: key, file and byte-size policy (D1, D16, O5)."""

from __future__ import annotations

import json
import typing as typ

import pytest

from ghillie.cli.errors import LocalInputError
from ghillie.cli.estate_input import (
    MAX_REQUEST_BODY_BYTES,
    encode_import_body,
    import_body,
    read_catalogue,
    validate_import_key,
)

if typ.TYPE_CHECKING:
    from pathlib import Path


def test_read_catalogue_strips_a_byte_order_mark(tmp_path: Path) -> None:
    """A BOM is an encoding artefact, not part of the document (D1)."""
    path = tmp_path / "catalogue.yaml"
    path.write_bytes(b"\xef\xbb\xbfversion: 1\n")

    assert read_catalogue(path) == "version: 1\n"


def test_read_catalogue_reports_an_unreadable_file(tmp_path: Path) -> None:
    """A missing file is a local input failure, not a traceback."""
    with pytest.raises(LocalInputError) as caught:
        read_catalogue(tmp_path / "absent.yaml")

    assert caught.value.code == "catalogue_file_unreadable"
    assert "absent.yaml" in caught.value.message


def test_read_catalogue_reports_invalid_utf8(tmp_path: Path) -> None:
    """Undecodable bytes are a local input failure with the documented code."""
    path = tmp_path / "invalid.yaml"
    path.write_bytes(b"version: 1\n# \xff\xfe\n")

    with pytest.raises(LocalInputError) as caught:
        read_catalogue(path)

    assert caught.value.code == "catalogue_file_unreadable"


def test_encode_import_body_omits_an_absent_estate_name() -> None:
    """The optional field stays off the wire when it was not supplied."""
    encoded = encode_import_body("version: 1\n", commit_sha="c1", estate_name=None)

    assert json.loads(encoded) == {
        "commit_sha": "c1",
        "catalogue_yaml": "version: 1\n",
    }


def test_encode_import_body_includes_the_estate_name() -> None:
    """A supplied name is sent unchanged (D18)."""
    encoded = encode_import_body(
        "version: 1\n", commit_sha="c1", estate_name="Wildside"
    )

    assert json.loads(encoded)["estate_name"] == "Wildside"


def test_encode_import_body_rejects_a_body_over_the_limit() -> None:
    """The exact serialized bytes are measured, not the character count (O5)."""
    document = "é" * MAX_REQUEST_BODY_BYTES
    assert len(document.encode("utf-8")) > MAX_REQUEST_BODY_BYTES, (
        "the padding must make bytes exceed the limit while characters do not"
    )

    with pytest.raises(LocalInputError) as caught:
        encode_import_body(document, commit_sha="c1", estate_name=None)

    assert caught.value.code == "request_too_large"
    assert str(MAX_REQUEST_BODY_BYTES) in caught.value.message


def test_validate_import_key_accepts_a_routable_key() -> None:
    """A key matching the creation pattern passes unchanged."""
    validate_import_key("2-5-2-estate")


@pytest.mark.parametrize("estate_key", ["", "-leading", "with space", "a" * 65])
def test_validate_import_key_rejects_an_unroutable_key(estate_key: str) -> None:
    """Every key the creation pattern excludes is a local input failure."""
    with pytest.raises(LocalInputError) as caught:
        validate_import_key(estate_key)

    assert caught.value.code == "invalid_estate_key"


def test_import_body_checks_the_key_before_reading_the_file(tmp_path: Path) -> None:
    """A bad key fails without touching the filesystem."""
    missing = tmp_path / "absent.yaml"

    with pytest.raises(LocalInputError) as caught:
        import_body("bad key", missing, commit_sha="c1", estate_name=None)

    assert caught.value.code == "invalid_estate_key"
