"""Unit tests for shared storage identifier generation."""

from __future__ import annotations

import typing as typ
import uuid

import pytest

from ghillie.catalogue.storage import (
    ComponentRecord,
    Estate,
    ProjectRecord,
    RepositoryRecord,
)
from ghillie.gold.storage import Report, ReportProject, ReportReview
from ghillie.silver.storage import Repository


def _parse_uuid7(value: str) -> uuid.UUID:
    """Parse a UUIDv7 string and assert canonical formatting."""
    parsed = uuid.UUID(value)
    assert str(parsed) == value
    assert parsed.version == 7
    return parsed


def _unix_ms_from_uuid7(value: uuid.UUID) -> int:
    """Extract the Unix-millisecond prefix from a UUIDv7 value."""
    return value.int >> 80


def test_new_uuid7_str_returns_canonical_uuid7() -> None:
    """Shared ID helper returns canonical UUIDv7 text."""
    from ghillie.common.ids import new_uuid7_str

    generated = new_uuid7_str()

    _parse_uuid7(generated)


def test_new_uuid7_str_has_non_decreasing_timestamp_prefix() -> None:
    """UUIDv7 helper embeds a non-decreasing millisecond timestamp prefix."""
    from ghillie.common.ids import new_uuid7_str

    first = _parse_uuid7(new_uuid7_str())
    second = _parse_uuid7(new_uuid7_str())

    assert _unix_ms_from_uuid7(second) >= _unix_ms_from_uuid7(first)


@pytest.mark.parametrize(
    "model_cls",
    [
        Estate,
        ProjectRecord,
        RepositoryRecord,
        ComponentRecord,
        Repository,
        ReportProject,
        Report,
        ReportReview,
    ],
)
def test_storage_model_id_defaults_generate_uuid7(model_cls: type[object]) -> None:
    """Storage primary-key defaults produce UUIDv7 strings."""
    default_factory = typ.cast("typ.Any", model_cls).__table__.c.id.default
    assert default_factory is not None

    generated = default_factory.arg(None)

    _parse_uuid7(generated)
