"""Local preparation of the estate import request.

The import verb validates and reads everything it can before a request is
sent: the estate key, the catalogue file, and the serialized byte size (D1,
D16, O5). Keeping that work out of the command module leaves the command with
nothing to do but delegate and present the outcome. Failures raise
:class:`~ghillie.cli.errors.LocalInputError`, which the command boundary maps
to exit code ``2``.
"""

from __future__ import annotations

import re
from pathlib import Path  # noqa: TC003 - Cyclopts resolves the annotation at runtime.

from ghillie.cli.control_plane import encode_json_body
from ghillie.cli.errors import LocalInputError
from ghillie.common.estate import NEW_ESTATE_KEY_PATTERN

MAX_REQUEST_BODY_BYTES = 1024 * 1024
"""Largest request body the service accepts (O5).

Duplicated from :mod:`ghillie.api.estate.resources` because the CLI must not
import the server package (O6); :mod:`tests.unit.cli.test_estate_import_commands`
asserts the two values stay equal. The estate-key pattern and the offset
ceiling are shared contracts rather than transport limits, so they live in
:mod:`ghillie.common.estate` and are imported here.
"""

_NEW_ESTATE_KEY_RE = re.compile(NEW_ESTATE_KEY_PATTERN)


def validate_import_key(estate_key: str) -> None:
    """Reject a key that cannot create an estate (D16).

    Raises
    ------
    LocalInputError
        If *estate_key* does not match
        :data:`~ghillie.common.estate.NEW_ESTATE_KEY_PATTERN`.

    """
    if _NEW_ESTATE_KEY_RE.fullmatch(estate_key):
        return
    message = f"estate key '{estate_key}' must match {NEW_ESTATE_KEY_PATTERN}"
    raise LocalInputError("invalid_estate_key", message)


def read_catalogue(catalogue_path: Path) -> str:
    """Read the catalogue as ``utf-8-sig``, stripping any byte-order mark.

    Raises
    ------
    LocalInputError
        If the file cannot be read or is not valid UTF-8.

    """
    try:
        return catalogue_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        message = f"cannot read catalogue file '{catalogue_path}': {exc}"
        raise LocalInputError("catalogue_file_unreadable", message) from exc


def encode_import_body(
    catalogue_yaml: str,
    *,
    commit_sha: str,
    estate_name: str | None,
) -> bytes:
    """Serialize the import request and enforce the service's byte limit (O5).

    Raises
    ------
    LocalInputError
        If the serialized body exceeds :data:`MAX_REQUEST_BODY_BYTES`.

    """
    body: dict[str, object] = {
        "commit_sha": commit_sha,
        "catalogue_yaml": catalogue_yaml,
    }
    if estate_name is not None:
        body["estate_name"] = estate_name
    encoded = encode_json_body(body)
    if len(encoded) > MAX_REQUEST_BODY_BYTES:
        message = (
            f"the request body is {len(encoded)} bytes; the limit is "
            f"{MAX_REQUEST_BODY_BYTES}"
        )
        raise LocalInputError("request_too_large", message)
    return encoded


def import_body(
    estate_key: str,
    catalogue_path: Path,
    *,
    commit_sha: str,
    estate_name: str | None,
) -> bytes:
    """Validate the local import inputs and return the encoded request body.

    Raises
    ------
    LocalInputError
        If the key is invalid, the file is unreadable, or the body is too
        large.

    """
    validate_import_key(estate_key)
    return encode_import_body(
        read_catalogue(catalogue_path),
        commit_sha=commit_sha,
        estate_name=estate_name,
    )
