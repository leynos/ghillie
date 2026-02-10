"""Unit tests for Markdown report rendering."""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest

from ghillie.gold.storage import Report, ReportScope
from ghillie.reporting.markdown import render_report_markdown


@dc.dataclass(frozen=True, slots=True)
class ReportTestMetadata:
    """Optional metadata overrides for test report creation.

    Encapsulates the five metadata fields that callers may wish to
    override when constructing reports for testing. Fields left as
    ``None`` receive sensible defaults in ``_build_report``.

    """

    model: str = "mock-v1"
    window_start: dt.datetime | None = None
    window_end: dt.datetime | None = None
    generated_at: dt.datetime | None = None
    report_id: str | None = None


_SENTINEL: typ.Final = object()

_DEFAULT_MACHINE_SUMMARY: dict[str, typ.Any] = {
    "summary": "Repository is progressing well.",
    "status": "on_track",
    "highlights": ["Feature A shipped", "Test coverage improved"],
    "risks": ["Dependency upgrade pending"],
    "next_steps": ["Review open PRs", "Plan next sprint"],
}


def _build_report(
    *,
    machine_summary: dict[str, typ.Any] | None | object = _SENTINEL,
    metadata: ReportTestMetadata | None = None,
) -> Report:
    """Create a Report instance for testing the Markdown renderer.

    Parameters
    ----------
    machine_summary
        Machine summary dict.  Defaults to a representative on-track
        report with highlights, risks, and next steps.  Pass ``None``
        or ``{}`` explicitly to test edge cases.
    metadata
        Optional metadata overrides for model, window dates,
        generated_at, and report_id.

    """
    meta = metadata or ReportTestMetadata()
    effective_summary = (
        _DEFAULT_MACHINE_SUMMARY if machine_summary is _SENTINEL else machine_summary
    )
    return Report(
        id=meta.report_id or str(uuid.uuid4()),
        scope=ReportScope.REPOSITORY,
        repository_id=str(uuid.uuid4()),
        window_start=meta.window_start or dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=meta.window_end or dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        generated_at=meta.generated_at or dt.datetime(2024, 7, 8, 12, 0, tzinfo=dt.UTC),
        model=meta.model,
        human_text="Raw LLM summary",
        machine_summary=effective_summary,
    )


class TestRenderReportMarkdown:
    """Tests for the render_report_markdown function."""

    def test_render_includes_title_with_repo_and_dates(self) -> None:
        """The title line contains owner/name and window date range."""
        report = _build_report()
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "acme/widget" in md, "Title should contain repo slug"
        assert "2024-07-01" in md, "Title should contain window start date"
        assert "2024-07-08" in md, "Title should contain window end date"
        lines = md.splitlines()
        assert lines[0].startswith("# "), "First line should be a level-1 heading"

    def test_render_includes_status_indicator(self) -> None:
        """The status section shows the correct status value."""
        report = _build_report(
            machine_summary={
                "summary": "Things are fine.",
                "status": "at_risk",
                "highlights": [],
                "risks": ["Something concerning"],
                "next_steps": [],
            }
        )
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "At Risk" in md, "Status indicator should show 'At Risk'"

    def test_render_includes_summary_section(self) -> None:
        """The summary section contains text from machine_summary."""
        report = _build_report()
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "## Summary" in md, "Summary heading should be present"
        assert "Repository is progressing well." in md, (
            "Summary text should appear in output"
        )

    def test_render_includes_highlights_as_bullets(self) -> None:
        """Each highlight appears as a bullet point."""
        report = _build_report()
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "## Highlights" in md, "Highlights heading should be present"
        assert "- Feature A shipped" in md, "First highlight should be a bullet"
        assert "- Test coverage improved" in md, "Second highlight should be a bullet"

    def test_render_includes_risks_as_bullets(self) -> None:
        """Each risk appears as a bullet point."""
        report = _build_report()
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "## Risks" in md, "Risks heading should be present"
        assert "- Dependency upgrade pending" in md, "Risk item should be a bullet"

    def test_render_includes_next_steps_as_bullets(self) -> None:
        """Each next step appears as a bullet point."""
        report = _build_report()
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "## Next steps" in md, "Next steps heading should be present"
        assert "- Review open PRs" in md, "First next step should be a bullet"
        assert "- Plan next sprint" in md, "Second next step should be a bullet"

    def test_render_includes_metadata_footer(self) -> None:
        """Footer includes model, generated_at, window, and report ID."""
        report_id = str(uuid.uuid4())
        report = _build_report(
            metadata=ReportTestMetadata(
                model="gpt-5.1-thinking",
                report_id=report_id,
            ),
        )
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "---" in md, "Footer should contain horizontal rule"
        assert "gpt-5.1-thinking" in md, "Footer should contain model name"
        assert report_id in md, "Footer should contain report ID"

    def test_render_omits_empty_sections(self) -> None:
        """Sections with empty lists are omitted entirely."""
        report = _build_report(
            machine_summary={
                "summary": "Quiet week.",
                "status": "on_track",
                "highlights": [],
                "risks": [],
                "next_steps": [],
            }
        )
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "## Summary" in md, "Summary should still be present"
        assert "## Highlights" not in md, "Empty highlights should be omitted"
        assert "## Risks" not in md, "Empty risks should be omitted"
        assert "## Next steps" not in md, "Empty next steps should be omitted"

    def test_render_handles_missing_machine_summary_keys(self) -> None:
        """Missing machine_summary keys are handled gracefully."""
        report = _build_report(machine_summary={"status": "unknown"})
        md = render_report_markdown(report, owner="acme", name="widget")

        # Should not raise and should still produce valid Markdown
        assert "acme/widget" in md, "Repo slug should be present"
        assert "Unknown" in md, "Status should fall back to Unknown"
        assert "## Summary" not in md, "Missing summary key should omit section"
        assert "## Highlights" not in md, "Missing highlights key should omit section"

    @pytest.mark.parametrize(
        ("machine_summary", "description"),
        [
            (None, "None"),
            ({}, "empty dict"),
        ],
        ids=["none_machine_summary", "empty_machine_summary"],
    )
    def test_render_handles_absent_machine_summary(
        self,
        machine_summary: dict[str, typ.Any] | None,
        description: str,
    ) -> None:
        """Absent or empty machine_summary produces a well-formed minimal report."""
        report = _build_report(machine_summary=machine_summary)
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "acme/widget" in md, f"Repo slug should be present ({description})"
        assert "Unknown" in md, f"Status should fall back to Unknown ({description})"
        assert "## Summary" not in md, f"Summary should be omitted ({description})"
        assert "## Highlights" not in md, (
            f"Highlights should be omitted ({description})"
        )
        assert "## Risks" not in md, f"Risks should be omitted ({description})"
        assert "## Next steps" not in md, (
            f"Next steps should be omitted ({description})"
        )
