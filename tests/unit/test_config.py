"""Unit tests for CLI config float coercion helpers."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from ghillie.cli.config import _coerce_float


class TestCoerceFloat:
    """Examples for supported and invalid float coercion inputs."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param("3.14", 3.14, id="str"),
            pytest.param(b"2.71", 2.71, id="bytes"),
            pytest.param(bytearray(b"1.0"), 1.0, id="bytearray"),
            pytest.param(Decimal("0.5"), 0.5, id="supports-float"),
            pytest.param(42, 42.0, id="int"),
        ],
    )
    def test_coerce_float_supported_values(
        self,
        value: object,
        expected: float,
    ) -> None:
        """Assert _coerce_float converts supported values to floats."""
        assert _coerce_float(value, field="request_timeout_s") == pytest.approx(
            expected
        )

    def test_coerce_float_invalid_value(self) -> None:
        """Assert _coerce_float reports the failing field name."""
        with pytest.raises(ValueError, match="request_timeout_s"):
            _coerce_float("nope", field="request_timeout_s")


class TestCoerceFloatProperties:
    """Property tests for string and integer float coercion."""

    @settings(max_examples=100)
    @given(st.floats(allow_nan=False, allow_infinity=False))
    def test_str_round_trip(self, value: float) -> None:
        """Round-trip finite floats through str before coercion."""
        assert _coerce_float(str(value), field="f") == pytest.approx(value)

    @settings(max_examples=100)
    @given(st.integers())
    def test_integer_matches_float_constructor(self, value: int) -> None:
        """Match float() for integers that Python can represent as float."""
        assume(-(10**308) <= value <= 10**308)
        assert _coerce_float(value, field="f") == pytest.approx(float(value))
