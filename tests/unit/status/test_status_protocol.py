"""Unit tests for StatusModel protocol compliance."""

from __future__ import annotations

from ghillie.status import MockStatusModel, StatusModel


class TestStatusModelProtocol:
    """Tests for StatusModel protocol compliance."""

    def test_mock_implements_protocol(self) -> None:
        """MockStatusModel is recognized as implementing StatusModel."""
        model = MockStatusModel()
        assert isinstance(model, StatusModel)

    def test_protocol_is_runtime_checkable(self) -> None:
        """StatusModel protocol supports isinstance checks."""

        class NotAStatusModel:
            pass

        assert not isinstance(NotAStatusModel(), StatusModel)
