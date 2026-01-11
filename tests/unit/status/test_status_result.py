"""Unit tests for RepositoryStatusResult and conversion helpers."""

from __future__ import annotations

import msgspec
import pytest

from ghillie.evidence.models import ReportStatus
from ghillie.status import RepositoryStatusResult, to_machine_summary


class TestRepositoryStatusResult:
    """Tests for RepositoryStatusResult struct."""

    def test_creation_with_required_fields(self) -> None:
        """RepositoryStatusResult can be created with required fields."""
        result = RepositoryStatusResult(
            summary="Repository is on track.",
            status=ReportStatus.ON_TRACK,
        )

        assert result.summary == "Repository is on track."
        assert result.status == ReportStatus.ON_TRACK
        assert result.highlights == ()
        assert result.risks == ()
        assert result.next_steps == ()

    def test_creation_with_all_fields(self) -> None:
        """RepositoryStatusResult can be created with all fields populated."""
        result = RepositoryStatusResult(
            summary="Repository is at risk due to pending issues.",
            status=ReportStatus.AT_RISK,
            highlights=("Delivered new API", "Improved test coverage"),
            risks=("Performance regression", "Missing documentation"),
            next_steps=("Address performance", "Update docs"),
        )

        assert result.summary == "Repository is at risk due to pending issues."
        assert result.status == ReportStatus.AT_RISK
        assert result.highlights == ("Delivered new API", "Improved test coverage")
        assert result.risks == ("Performance regression", "Missing documentation")
        assert result.next_steps == ("Address performance", "Update docs")

    def test_is_frozen(self) -> None:
        """RepositoryStatusResult is immutable."""
        result = RepositoryStatusResult(
            summary="Test",
            status=ReportStatus.ON_TRACK,
        )

        with pytest.raises(AttributeError):
            result.summary = "Modified"  # type: ignore[misc]

    def test_json_serialization_roundtrip(self) -> None:
        """RepositoryStatusResult can be serialized to and from JSON."""
        original = RepositoryStatusResult(
            summary="Test summary",
            status=ReportStatus.AT_RISK,
            highlights=("Highlight 1",),
            risks=("Risk 1",),
            next_steps=("Step 1",),
        )

        encoded = msgspec.json.encode(original)
        decoded = msgspec.json.decode(encoded, type=RepositoryStatusResult)

        assert decoded.summary == original.summary
        assert decoded.status == original.status
        assert decoded.highlights == original.highlights
        assert decoded.risks == original.risks
        assert decoded.next_steps == original.next_steps


class TestToMachineSummary:
    """Tests for to_machine_summary conversion helper."""

    def test_converts_to_dict_format(self) -> None:
        """to_machine_summary produces dict for Report.machine_summary."""
        result = RepositoryStatusResult(
            summary="Repository on track",
            status=ReportStatus.ON_TRACK,
            highlights=("Feature A", "Feature B"),
            risks=("Risk X",),
            next_steps=("Next 1", "Next 2"),
        )

        summary = to_machine_summary(result)

        assert summary["summary"] == "Repository on track"
        assert summary["status"] == "on_track"
        assert summary["highlights"] == ["Feature A", "Feature B"]
        assert summary["risks"] == ["Risk X"]
        assert summary["next_steps"] == ["Next 1", "Next 2"]

    def test_empty_collections_become_empty_lists(self) -> None:
        """Empty tuple collections become empty lists in dict."""
        result = RepositoryStatusResult(
            summary="Minimal",
            status=ReportStatus.UNKNOWN,
        )

        summary = to_machine_summary(result)

        assert summary["highlights"] == []
        assert summary["risks"] == []
        assert summary["next_steps"] == []
