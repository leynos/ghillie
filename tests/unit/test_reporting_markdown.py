"""Unit tests for Markdown report rendering."""

from __future__ import annotations

import datetime as dt
import uuid

from ghillie.gold.storage import Report, ReportScope
from ghillie.reporting.markdown import render_report_markdown


def _build_report(  # noqa: PLR0913
    *,
    machine_summary: dict | None = None,
    model: str = "mock-v1",
    window_start: dt.datetime | None = None,
    window_end: dt.datetime | None = None,
    generated_at: dt.datetime | None = None,
    report_id: str | None = None,
) -> Report:
    """Create a Report instance for testing the Markdown renderer."""
    return Report(
        id=report_id or str(uuid.uuid4()),
        scope=ReportScope.REPOSITORY,
        repository_id=str(uuid.uuid4()),
        window_start=window_start or dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=window_end or dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        generated_at=generated_at or dt.datetime(2024, 7, 8, 12, 0, tzinfo=dt.UTC),
        model=model,
        human_text="Raw LLM summary",
        machine_summary=machine_summary
        or {
            "summary": "Repository is progressing well.",
            "status": "on_track",
            "highlights": ["Feature A shipped", "Test coverage improved"],
            "risks": ["Dependency upgrade pending"],
            "next_steps": ["Review open PRs", "Plan next sprint"],
        },
    )


class TestRenderReportMarkdown:
    """Tests for the render_report_markdown function."""

    def test_render_includes_title_with_repo_and_dates(self) -> None:
        """The title line contains owner/name and window date range."""
        report = _build_report()
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "acme/widget" in md
        assert "2024-07-01" in md
        assert "2024-07-08" in md
        # Title should be a level-1 heading
        lines = md.splitlines()
        assert lines[0].startswith("# ")

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

        assert "At Risk" in md

    def test_render_includes_summary_section(self) -> None:
        """The summary section contains text from machine_summary."""
        report = _build_report()
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "## Summary" in md
        assert "Repository is progressing well." in md

    def test_render_includes_highlights_as_bullets(self) -> None:
        """Each highlight appears as a bullet point."""
        report = _build_report()
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "## Highlights" in md
        assert "- Feature A shipped" in md
        assert "- Test coverage improved" in md

    def test_render_includes_risks_as_bullets(self) -> None:
        """Each risk appears as a bullet point."""
        report = _build_report()
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "## Risks" in md
        assert "- Dependency upgrade pending" in md

    def test_render_includes_next_steps_as_bullets(self) -> None:
        """Each next step appears as a bullet point."""
        report = _build_report()
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "## Next steps" in md
        assert "- Review open PRs" in md
        assert "- Plan next sprint" in md

    def test_render_includes_metadata_footer(self) -> None:
        """Footer includes model, generated_at, window, and report ID."""
        report_id = str(uuid.uuid4())
        report = _build_report(
            model="gpt-5.1-thinking",
            report_id=report_id,
        )
        md = render_report_markdown(report, owner="acme", name="widget")

        assert "---" in md
        assert "gpt-5.1-thinking" in md
        assert report_id in md

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

        assert "## Summary" in md
        assert "## Highlights" not in md
        assert "## Risks" not in md
        assert "## Next steps" not in md

    def test_render_handles_missing_machine_summary_keys(self) -> None:
        """Missing machine_summary keys are handled gracefully."""
        report = _build_report(machine_summary={"status": "unknown"})
        md = render_report_markdown(report, owner="acme", name="widget")

        # Should not raise and should still produce valid Markdown
        assert "acme/widget" in md
        assert "Unknown" in md
        assert "## Summary" not in md
        assert "## Highlights" not in md
